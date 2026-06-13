"""Advance endpoints: create, fetch, list, approve, decline, disburse,
manual-recoup, write-off.

Approve precondition order follows PRD §3.5 prose (which §2.11 explicitly defers
to for business rules): employment_status ACTIVE -> advance_eligibility ELIGIBLE
-> employer not FROZEN -> cooling-off -> period cap -> floor (after the clamp).
"""
from flask import Blueprint, request

import db
import errors
from middleware import authenticate, require_role
from response import object_response, array_response
from services import domain, serialize, validate
from timeutil import parse_iso8601
import clock

bp = Blueprint("advances", __name__)

SPEEDS = {"STANDARD", "INSTANT"}


@bp.route("/advances", methods=["POST"])
def create_advance():
    user_id, role = authenticate()
    require_role(role, {"Worker", "PayrollOfficer"})
    body = validate.get_body()

    worker_id = validate.require_str(body, "worker_id")
    pay_period_id = validate.require_str(body, "pay_period_id")

    # Worker self-service ownership (PRD §2.1): a Worker may only create an advance
    # whose worker_id == X-User-ID.
    if role == "Worker" and worker_id != user_id:
        raise errors.unauthorized()

    worker = db.workers.get(worker_id)
    period = db.pay_periods.get(pay_period_id)
    # Cross-employer / referential integrity (priority 4).
    if worker is None or period is None:
        raise errors.cross_employer("Body foreign key does not resolve")
    if worker["employer_id"] != period["employer_id"]:
        raise errors.cross_employer("worker and pay_period belong to different employers")

    # Body well-formedness (priority 5).
    requested = validate.require_int(body, "requested_principal_cents", minimum=1)
    speed = validate.optional_enum(body, "disbursement_speed", SPEEDS, default="STANDARD")
    tip = validate.optional_int(body, "tip_cents", default=0, minimum=0)
    expected_version = validate.require_int(body, "expected_worker_version")

    # OCC against the worker's current version (priority 7).
    if expected_version != worker["version"]:
        raise errors.stale_version("Worker version is stale")

    common = db.new_common_fields()
    advance = {
        **common,
        "employer_id": worker["employer_id"],
        "worker_id": worker_id,
        "pay_period_id": pay_period_id,
        "requested_principal_cents": requested,
        "principal_cents": 0,
        "disbursement_speed": speed,
        "tip_cents": tip,
        "expedite_fee_cents": 0,
        "total_fee_cents": 0,
        "disbursed_amount_cents": 0,
        "recoup_target_cents": 0,
        "amount_recouped_cents": 0,
        "principal_outstanding_cents": 0,
        "requested_at": clock_now_iso(),
        "disbursed_at": None,
        "status": "REQUESTED",
    }
    db.advances[advance["id"]] = advance

    # Creating an advance increments the target worker's version by 1 (PRD §3.5).
    db.touch(worker)

    return object_response(serialize.advance(advance), status=201)


def clock_now_iso():
    from timeutil import format_iso8601
    return format_iso8601(clock.now())


@bp.route("/advances/<advance_id>", methods=["GET"])
def get_advance(advance_id):
    user_id, role = authenticate()
    require_role(role, {"Worker", "PayrollOfficer", "ComplianceOfficer"})
    advance = db.advances.get(advance_id)
    if advance is None:
        raise errors.not_found()
    if role == "Worker" and advance["worker_id"] != user_id:
        raise errors.unauthorized()
    return object_response(serialize.advance(advance))


@bp.route("/advances", methods=["GET"])
def list_advances():
    user_id, role = authenticate()
    require_role(role, {"PayrollOfficer", "ComplianceOfficer", "Worker"})
    limit, offset = validate.pagination()
    w_filter = request.args.get("worker_id")
    pp_filter = request.args.get("pay_period_id")
    emp_filter = request.args.get("employer_id")
    items = []
    for a in db.advances.values():
        if role == "Worker" and a["worker_id"] != user_id:
            continue
        if w_filter is not None and a["worker_id"] != w_filter:
            continue
        if pp_filter is not None and a["pay_period_id"] != pp_filter:
            continue
        if emp_filter is not None and a["employer_id"] != emp_filter:
            continue
        items.append(a)
    page, total = validate.paginate(items, limit, offset)
    return array_response([serialize.advance(a) for a in page], limit, offset, total)


def _load_for_transition(advance_id):
    _, role = authenticate()
    advance = db.advances.get(advance_id)
    if advance is None:
        raise errors.not_found()
    return advance, role


@bp.route("/advances/<advance_id>/approve", methods=["POST"])
def approve_advance(advance_id):
    user_id, role = authenticate()
    require_role(role, {"PayrollOfficer"})
    advance = db.advances.get(advance_id)
    if advance is None:
        raise errors.not_found()
    if advance["status"] != "REQUESTED":
        raise errors.invalid_state()

    worker = db.workers.get(advance["worker_id"])
    employer = db.employers.get(advance["employer_id"])
    period = db.pay_periods.get(advance["pay_period_id"])

    # PRD §3.5 precondition order.
    if worker["employment_status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_WORKER_NOT_ACTIVE, 409, "Worker is not ACTIVE")
    if domain.derive_advance_eligibility(worker) != "ELIGIBLE":
        raise errors.ApiError(errors.ERR_WORKER_ON_HOLD, 409, "Worker is ON_HOLD")
    if domain.derive_posture(employer) == "FROZEN":
        raise errors.ApiError(errors.ERR_EMPLOYER_FROZEN, 409, "Employer is frozen")

    # Cooling-off: elapsed from the worker's most-recent DISBURSED advance's
    # disbursed_at to server clock must be >= cooling_off_hours (PRD §3.5).
    if not _cooling_off_satisfied(worker, employer):
        raise errors.ApiError(errors.ERR_COOLING_OFF_ACTIVE, 409, "Cooling-off window active")

    if domain.period_advance_count(worker) >= employer["per_period_advance_cap_count"]:
        raise errors.ApiError(errors.ERR_PERIOD_CAP_REACHED, 409, "Period advance cap reached")

    # Clamp principal (PRD §3.6).
    tier = domain.select_tier(employer["id"], domain.compute_tenure_days(worker))
    if tier is None:
        # No tier => principal treated as 0 => fails floor check.
        raise errors.ApiError(errors.ERR_BELOW_FLOOR, 422, "No advance limit policy tier qualifies")
    principal = domain.clamp_principal(advance, worker, period, tier)
    if principal < tier["per_advance_floor_cents"]:
        raise errors.ApiError(errors.ERR_BELOW_FLOOR, 422, "Clamped principal below tier floor")

    # Compute fees (PRD §3.7).
    fee_schedule = domain.active_fee_schedule(employer["id"])
    if fee_schedule is None:
        # No fee schedule: STANDARD has 0 expedite; INSTANT pricing requires one.
        # Treat absence as zero expedite + tip ignored (no tip policy known).
        expedite, total_fee = 0, 0
    else:
        expedite, total_fee = domain.compute_fees(advance, principal, fee_schedule)

    advance["principal_cents"] = principal
    advance["expedite_fee_cents"] = expedite
    advance["total_fee_cents"] = total_fee
    advance["recoup_target_cents"] = principal + total_fee
    advance["disbursed_amount_cents"] = principal
    advance["status"] = "APPROVED"
    # Record the approver's X-User-ID for segregation-of-duties checks (PRD §2.8).
    advance["approved_by_user_id"] = user_id
    db.touch(advance)
    # Approving moves the worker into COMMITTED state for available-earnings; the
    # worker's computed counters change, so bump its version.
    db.touch(worker)
    return object_response(serialize.advance(advance))


def _cooling_off_satisfied(worker, employer):
    last_disbursed_at = None
    for a in domain.worker_advances(worker["id"]):
        if a.get("disbursed_at") and a["status"] in domain.DISBURSED_OR_BEYOND:
            dt = parse_iso8601(a["disbursed_at"])
            if last_disbursed_at is None or dt > last_disbursed_at:
                last_disbursed_at = dt
    if last_disbursed_at is None:
        return True
    elapsed_hours = (clock.now() - last_disbursed_at).total_seconds() / 3600.0
    return elapsed_hours >= employer["cooling_off_hours"]


@bp.route("/advances/<advance_id>/decline", methods=["POST"])
def decline_advance(advance_id):
    _, role = authenticate()
    require_role(role, {"PayrollOfficer"})
    advance = db.advances.get(advance_id)
    if advance is None:
        raise errors.not_found()
    if advance["status"] != "REQUESTED":
        raise errors.invalid_state()
    advance["status"] = "DECLINED"
    advance["principal_cents"] = 0
    advance["principal_outstanding_cents"] = 0
    db.touch(advance)
    return object_response(serialize.advance(advance))


@bp.route("/advances/<advance_id>/disburse", methods=["POST"])
def disburse_advance(advance_id):
    _, role = authenticate()
    require_role(role, {"PayrollOfficer"})
    advance = db.advances.get(advance_id)
    if advance is None:
        raise errors.not_found()
    if advance["status"] != "APPROVED":
        raise errors.invalid_state()

    employer = db.employers.get(advance["employer_id"])
    # PRD §3.8 prose lists the funding check before the frozen check; §2.11 defers
    # business-rule ordering to the §3 workflow prose, which is authoritative.
    if employer["funding_balance_cents"] < advance["recoup_target_cents"]:
        raise errors.ApiError(errors.ERR_INSUFFICIENT_FUNDING, 402, "Insufficient funding")
    if domain.derive_posture(employer) == "FROZEN":
        raise errors.ApiError(errors.ERR_EMPLOYER_FROZEN, 409, "Employer is frozen")

    advance["disbursed_at"] = clock_now_iso()
    employer["funding_balance_cents"] -= advance["recoup_target_cents"]
    advance["principal_outstanding_cents"] = advance["recoup_target_cents"]
    advance["status"] = "DISBURSED"
    db.touch(advance)
    db.touch(employer)
    # Recompute worker counters (lifetime/period count) -> version bump.
    worker = db.workers.get(advance["worker_id"])
    if worker is not None:
        db.touch(worker)
    # Recompute employer outstanding + posture (may flip HEALTHY -> RESTRICTED).
    domain.refresh_employer(employer)
    return object_response(serialize.advance(advance))


@bp.route("/advances/<advance_id>/manual-recoup", methods=["POST"])
def manual_recoup(advance_id):
    _, role = authenticate()
    require_role(role, {"PayrollOfficer"})
    advance = db.advances.get(advance_id)
    if advance is None:
        raise errors.not_found()
    if advance["status"] != "DEFAULTED":
        raise errors.invalid_state()

    body = validate.get_body()
    amount = validate.require_int(body, "amount_cents")

    employer = db.employers.get(advance["employer_id"])

    # PRD §3.9 prose order: the over-recoup range check is stated before the
    # frozen check, so it is evaluated first.
    if not (0 < amount <= advance["principal_outstanding_cents"]):
        raise errors.ApiError(errors.ERR_OVER_RECOUP, 422, "Recoup amount out of range")

    # Frozen unless this recovery clears the period discrepancy (PRD §3.9).
    if domain.derive_posture(employer) == "FROZEN" and not _recovery_clears_discrepancy(advance, amount):
        raise errors.ApiError(errors.ERR_EMPLOYER_FROZEN, 409, "Employer is frozen")

    # Create a Repayment row tied to the period's posted-or-prior batch.
    batch = _period_recoup_batch(advance["pay_period_id"])
    fee_owed = max(0, advance["total_fee_cents"] - domain.fee_recouped_so_far(advance["id"]))
    fee_slice = min(amount, fee_owed)
    principal_slice = amount - fee_slice
    if fee_slice > 0:
        _create_repayment(advance["id"], batch, fee_slice, "FEE")
    if principal_slice > 0:
        _create_repayment(advance["id"], batch, principal_slice, "PRINCIPAL")

    advance["status"] = "RECOUPING"
    domain.recompute_advance_recoup(advance)
    db.touch(advance)

    # Recompute the period's statement drift (DEFAULTED write-back hop).
    domain.recompute_period_statement(advance["pay_period_id"], create_if_absent=False)

    # If outstanding hit 0, settle (RECOUPING -> SETTLED cascade).
    domain.maybe_settle(advance)

    # A manual-recoup adds to actual_recouped via the batch total; refresh employer
    # posture (a clearing recovery may lift FROZEN once no discrepancy remains).
    domain.refresh_employer(employer)

    return object_response(serialize.advance(advance))


def _recovery_clears_discrepancy(advance, amount):
    """True if recovering `amount` would drive the period statement drift to 0."""
    stmt = domain.get_period_statement(advance["pay_period_id"])
    if stmt is None:
        return False
    # drift_after = drift_before - amount (actual_recouped increases by amount).
    return (stmt["drift_cents"] - amount) == 0


def _period_recoup_batch(pay_period_id):
    """Return the period's POSTED/RECONCILED batch (the one that recouped) for tying
    a manual-recoup Repayment row to. Falls back to any batch for the period."""
    posted = None
    any_batch = None
    for b in db.repayment_batches.values():
        if b["pay_period_id"] != pay_period_id:
            continue
        any_batch = b
        if b["status"] in ("POSTED", "RECONCILED"):
            posted = b
    return posted or any_batch


def _create_repayment(advance_id, batch, amount, applied_to):
    ledger = db.new_ledger_fields()
    repayment = {
        **ledger,
        "advance_id": advance_id,
        "repayment_batch_id": batch["id"] if batch else None,
        "amount_cents": amount,
        "applied_to": applied_to,
    }
    db.repayments[repayment["id"]] = repayment
    if batch is not None:
        # Manual-recoup repayments count toward the batch total/reconciliation
        # actual_recouped (they are tied to the period's posted/prior batch).
        batch["total_recouped_cents"] = sum(
            r["amount_cents"] for r in db.repayments.values()
            if r["repayment_batch_id"] == batch["id"]
        )
        distinct = {r["advance_id"] for r in db.repayments.values()
                    if r["repayment_batch_id"] == batch["id"]}
        batch["advance_count"] = len(distinct)
        db.touch(batch)
    return repayment


@bp.route("/advances/<advance_id>/write-off", methods=["POST"])
def write_off_advance(advance_id):
    _, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    advance = db.advances.get(advance_id)
    if advance is None:
        raise errors.not_found()
    if advance["status"] != "DEFAULTED":
        raise errors.invalid_state()
    if advance["principal_outstanding_cents"] <= 0:
        raise errors.ApiError(errors.ERR_NOTHING_TO_WRITE_OFF, 409, "Nothing to write off")
    period = db.pay_periods.get(advance["pay_period_id"])
    if period is None or period["status"] != "DISBURSED":
        raise errors.ApiError(errors.ERR_PERIOD_NOT_DISBURSED, 409, "Period not disbursed")

    written_off = advance["principal_outstanding_cents"]
    advance["written_off_amount_cents"] = written_off
    advance["principal_outstanding_cents"] = 0
    advance["status"] = "WRITTEN_OFF"
    db.touch(advance)

    # Worker stays ON_HOLD (WRITTEN_OFF remains in the penalty set) — refresh anyway.
    worker = db.workers.get(advance["worker_id"])
    if worker is not None:
        domain.refresh_worker_eligibility(worker)

    # Recompute statement written_off + drift; then employer outstanding + posture.
    domain.recompute_period_statement(advance["pay_period_id"], create_if_absent=True)
    employer = db.employers.get(advance["employer_id"])
    if employer is not None:
        domain.refresh_employer(employer)

    return object_response(serialize.advance(advance))
