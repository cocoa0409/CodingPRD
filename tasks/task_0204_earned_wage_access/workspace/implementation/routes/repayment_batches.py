"""RepaymentBatch + Repayment endpoints.

Posting a batch runs the payday-recoup waterfall (PRD §3.10): candidates are the
period's advances in {DISBURSED, RECOUPING}, sorted by (disbursed_at asc,
created_at asc); a per-worker recoup cap = floor(gross_accrued_for_worker *
max_advance_pct_of_available); within each advance, fee is recouped before
principal.
"""
from flask import Blueprint, request

import db
import errors
from middleware import authenticate, require_role
from response import object_response, array_response
from services import domain, serialize, validate
from services.money import floor_fraction
from timeutil import parse_iso8601

bp = Blueprint("repayment_batches", __name__)


@bp.route("/repayment-batches", methods=["POST"])
def create_batch():
    _, role = authenticate()
    require_role(role, {"PayrollOfficer"})
    body = validate.get_body()
    pay_period_id = validate.require_str(body, "pay_period_id")
    period = db.pay_periods.get(pay_period_id)
    # FK must resolve (priority 4 cross-employer / referential).
    if period is None:
        raise errors.cross_employer("pay_period_id does not resolve")

    common = db.new_common_fields()
    batch = {
        **common,
        "pay_period_id": pay_period_id,
        "employer_id": period["employer_id"],
        "total_recouped_cents": 0,
        "advance_count": 0,
        "posted_by_user_id": None,
        "status": "DRAFT",
    }
    db.repayment_batches[batch["id"]] = batch
    return object_response(serialize.repayment_batch(batch), status=201)


@bp.route("/repayment-batches/<batch_id>", methods=["GET"])
def get_batch(batch_id):
    _, role = authenticate()
    require_role(role, {"PayrollOfficer", "ComplianceOfficer"})
    batch = db.repayment_batches.get(batch_id)
    if batch is None:
        raise errors.not_found()
    return object_response(serialize.repayment_batch(batch))


@bp.route("/repayment-batches", methods=["GET"])
def list_batches():
    _, role = authenticate()
    require_role(role, {"PayrollOfficer", "ComplianceOfficer"})
    limit, offset = validate.pagination()
    pp_filter = request.args.get("pay_period_id")
    emp_filter = request.args.get("employer_id")
    items = []
    for b in db.repayment_batches.values():
        if pp_filter is not None and b["pay_period_id"] != pp_filter:
            continue
        if emp_filter is not None and b["employer_id"] != emp_filter:
            continue
        items.append(b)
    page, total = validate.paginate(items, limit, offset)
    return array_response([serialize.repayment_batch(b) for b in page], limit, offset, total)


@bp.route("/repayment-batches/<batch_id>/post", methods=["POST"])
def post_batch(batch_id):
    user_id, role = authenticate()
    require_role(role, {"PayrollOfficer"})
    batch = db.repayment_batches.get(batch_id)
    if batch is None:
        raise errors.not_found()

    body = validate.get_body()
    expected_version = validate.require_int(body, "expected_repaymentbatch_version")

    # State legality (priority 6).
    if batch["status"] != "DRAFT":
        raise errors.invalid_state()

    period = db.pay_periods.get(batch["pay_period_id"])

    # OCC (priority 7).
    if expected_version != batch["version"]:
        raise errors.stale_version("Batch version is stale")

    # Segregation of duties (priority 8): poster must not be the approver of any
    # advance in the period. (Approver identity is the X-User-ID that approved.)
    for a in domain.period_advances(batch["pay_period_id"]):
        if a.get("approved_by_user_id") == user_id:
            raise errors.segregation_of_duties("Poster approved an advance in this period")

    # Period must be LOCKED (PRD §3.8).
    if period is None or period["status"] != "LOCKED":
        raise errors.ApiError(errors.ERR_PERIOD_NOT_LOCKED, 409, "Period is not LOCKED")

    # No other batch for the period already POSTED/RECONCILED (PRD §3.8).
    for b in db.repayment_batches.values():
        if b["id"] == batch_id:
            continue
        if b["pay_period_id"] == batch["pay_period_id"] and b["status"] in ("POSTED", "RECONCILED"):
            raise errors.ApiError(errors.ERR_BATCH_ALREADY_POSTED, 409,
                                  "A batch for this period is already posted")

    # Run the waterfall.
    _run_waterfall(batch, period)

    batch["status"] = "POSTED"
    batch["posted_by_user_id"] = user_id
    _recompute_batch_totals(batch)
    db.touch(batch)

    # Recompute the period's reconciliation statement (PRD §3.11 trigger on post).
    domain.recompute_period_statement(batch["pay_period_id"], create_if_absent=False)

    # Settlement cascades may have credited the funding pool; refresh employer.
    employer = db.employers.get(batch["employer_id"])
    if employer is not None:
        domain.refresh_employer(employer)

    return object_response(serialize.repayment_batch(batch))


def _run_waterfall(batch, period):
    pay_period_id = batch["pay_period_id"]
    candidates = [
        a for a in domain.period_advances(pay_period_id)
        if a["status"] in ("DISBURSED", "RECOUPING")
    ]
    # Sort by (disbursed_at asc, created_at asc); use _seq for the created_at tiebreak.
    def sort_key(a):
        d = a.get("disbursed_at")
        d_key = parse_iso8601(d) if d else parse_iso8601("1970-01-01T00:00:00Z")
        return (d_key, a["_seq"])
    candidates.sort(key=sort_key)

    employer = db.employers.get(batch["employer_id"])
    pct = employer["max_advance_pct_of_available"]

    per_worker_cap = {}
    already = {}
    for a in candidates:
        wid = a["worker_id"]
        if wid not in per_worker_cap:
            worker = db.workers.get(wid)
            gross = domain.gross_for_worker_in_period(pay_period_id, worker)
            per_worker_cap[wid] = floor_fraction(gross, pct)
            already[wid] = 0

    settled_during = []
    for a in candidates:
        wid = a["worker_id"]
        room = max(0, per_worker_cap[wid] - already[wid])
        owed = a["recoup_target_cents"] - a["amount_recouped_cents"]
        take = min(owed, room)
        if take <= 0:
            continue
        fee_owed = max(0, a["total_fee_cents"] - domain.fee_recouped_so_far(a["id"]))
        fee_slice = min(take, fee_owed)
        principal_slice = take - fee_slice
        if fee_slice > 0:
            _make_repayment(a["id"], batch["id"], fee_slice, "FEE")
        if principal_slice > 0:
            _make_repayment(a["id"], batch["id"], principal_slice, "PRINCIPAL")
        a["amount_recouped_cents"] += take
        already[wid] += take
        # First repayment applied -> DISBURSED -> RECOUPING.
        if a["status"] == "DISBURSED":
            a["status"] = "RECOUPING"
        a["principal_outstanding_cents"] = a["recoup_target_cents"] - a["amount_recouped_cents"]
        db.touch(a)
        settled_during.append(a)

    # Cascade: any advance driven to 0 outstanding -> SETTLED (credits funding).
    for a in settled_during:
        domain.maybe_settle(a)


def _make_repayment(advance_id, batch_id, amount, applied_to):
    ledger = db.new_ledger_fields()
    repayment = {
        **ledger,
        "advance_id": advance_id,
        "repayment_batch_id": batch_id,
        "amount_cents": amount,
        "applied_to": applied_to,
    }
    db.repayments[repayment["id"]] = repayment
    return repayment


def _recompute_batch_totals(batch):
    rows = [r for r in db.repayments.values() if r["repayment_batch_id"] == batch["id"]]
    batch["total_recouped_cents"] = sum(r["amount_cents"] for r in rows)
    batch["advance_count"] = len({r["advance_id"] for r in rows})


@bp.route("/repayment-batches/<batch_id>/cancel", methods=["POST"])
def cancel_batch(batch_id):
    _, role = authenticate()
    require_role(role, {"PayrollOfficer"})
    batch = db.repayment_batches.get(batch_id)
    if batch is None:
        raise errors.not_found()
    if batch["status"] != "DRAFT":
        raise errors.invalid_state()
    batch["status"] = "CANCELLED"
    db.touch(batch)
    return object_response(serialize.repayment_batch(batch))


# ---------------------------------------------------------------------------
# Repayment (read-only)
# ---------------------------------------------------------------------------
@bp.route("/repayments/<repayment_id>", methods=["GET"])
def get_repayment(repayment_id):
    _, role = authenticate()
    require_role(role, {"PayrollOfficer", "ComplianceOfficer"})
    repayment = db.repayments.get(repayment_id)
    if repayment is None:
        raise errors.not_found()
    return object_response(serialize.repayment(repayment))


@bp.route("/repayments", methods=["GET"])
def list_repayments():
    user_id, role = authenticate()
    require_role(role, {"PayrollOfficer", "ComplianceOfficer", "Worker"})
    limit, offset = validate.pagination()
    adv_filter = request.args.get("advance_id")
    batch_filter = request.args.get("repayment_batch_id")
    items = []
    for r in db.repayments.values():
        if adv_filter is not None and r["advance_id"] != adv_filter:
            continue
        if batch_filter is not None and r["repayment_batch_id"] != batch_filter:
            continue
        if role == "Worker":
            adv = db.advances.get(r["advance_id"])
            if adv is None or adv["worker_id"] != user_id:
                continue
        items.append(r)
    page, total = validate.paginate(items, limit, offset)
    return array_response([serialize.repayment(r) for r in page], limit, offset, total)
