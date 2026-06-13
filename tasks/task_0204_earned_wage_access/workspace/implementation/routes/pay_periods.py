"""PayPeriod endpoints + lock/reopen/run-payday transitions."""
from flask import Blueprint, request

import db
import errors
from middleware import authenticate, require_role
from response import object_response, array_response
from services import domain, serialize, validate
from timeutil import parse_iso8601, format_iso8601
import clock

bp = Blueprint("pay_periods", __name__)


@bp.route("/pay-periods", methods=["POST"])
def create_pay_period():
    _, role = authenticate()
    require_role(role, {"PayrollOfficer"})
    body = validate.get_body()
    employer_id = validate.require_str(body, "employer_id")
    employer = db.employers.get(employer_id)
    if employer is None:
        raise errors.not_found("Employer not found")
    start_at = validate.require_datetime(body, "start_at")
    end_at = validate.require_datetime(body, "end_at")
    if not (end_at > start_at):
        raise errors.invalid_request("end_at must be strictly after start_at")

    # Half-open overlap check vs other non-DISBURSED periods of the same employer
    # (PRD §3.3, validation priority 14.7). Abutting (prev.end == next.start) allowed.
    for p in db.pay_periods.values():
        if p["employer_id"] != employer_id:
            continue
        if p["status"] == "DISBURSED":
            continue
        p_start = parse_iso8601(p["start_at"])
        p_end = parse_iso8601(p["end_at"])
        # [start_at, end_at) overlaps [p_start, p_end) iff start_at < p_end and p_start < end_at
        if start_at < p_end and p_start < end_at:
            raise errors.ApiError(errors.ERR_PERIOD_OVERLAP, 409,
                                  "Pay period interval overlaps an existing period")

    # period_index: monotonic per-employer counter starting at 0.
    existing = [p for p in db.pay_periods.values() if p["employer_id"] == employer_id]
    next_index = len(existing)

    common = db.new_common_fields()
    period = {
        **common,
        "employer_id": employer_id,
        "period_index": next_index,
        "start_at": body["start_at"],
        "end_at": body["end_at"],
        "gross_accrued_cents": 0,
        "status": "OPEN",
        "locked_at": None,
        "disbursed_at": None,
    }
    db.pay_periods[period["id"]] = period
    return object_response(serialize.pay_period(period), status=201)


@bp.route("/pay-periods/<pay_period_id>", methods=["GET"])
def get_pay_period(pay_period_id):
    _, role = authenticate()
    require_role(role, {"PayrollOfficer", "ComplianceOfficer"})
    period = db.pay_periods.get(pay_period_id)
    if period is None:
        raise errors.not_found()
    return object_response(serialize.pay_period(period))


@bp.route("/pay-periods", methods=["GET"])
def list_pay_periods():
    _, role = authenticate()
    require_role(role, {"PayrollOfficer", "ComplianceOfficer"})
    limit, offset = validate.pagination()
    emp_filter = request.args.get("employer_id")
    items = [
        p for p in db.pay_periods.values()
        if emp_filter is None or p["employer_id"] == emp_filter
    ]
    page, total = validate.paginate(items, limit, offset)
    return array_response([serialize.pay_period(p) for p in page], limit, offset, total)


def _frozen(employer):
    return domain.derive_posture(employer) == "FROZEN"


@bp.route("/pay-periods/<pay_period_id>/lock", methods=["POST"])
def lock_period(pay_period_id):
    _, role = authenticate()
    require_role(role, {"PayrollOfficer"})
    period = db.pay_periods.get(pay_period_id)
    if period is None:
        raise errors.not_found()
    if period["status"] != "OPEN":
        raise errors.invalid_state()
    employer = db.employers.get(period["employer_id"])
    if _frozen(employer):
        raise errors.ApiError(errors.ERR_EMPLOYER_FROZEN, 409, "Employer is frozen")
    period["status"] = "LOCKED"
    period["locked_at"] = format_iso8601(clock.now())
    period["gross_accrued_cents"] = domain.gross_accrued_for_period(period)
    db.touch(period)
    return object_response(serialize.pay_period(period))


@bp.route("/pay-periods/<pay_period_id>/reopen", methods=["POST"])
def reopen_period(pay_period_id):
    _, role = authenticate()
    require_role(role, {"PayrollOfficer"})
    period = db.pay_periods.get(pay_period_id)
    if period is None:
        raise errors.not_found()
    if period["status"] != "LOCKED":
        raise errors.invalid_state()
    # Blocked when any batch for the period is POSTED or RECONCILED (PRD §3.3).
    for b in db.repayment_batches.values():
        if b["pay_period_id"] == pay_period_id and b["status"] in ("POSTED", "RECONCILED"):
            raise errors.ApiError(errors.ERR_PERIOD_HAS_POSTED_BATCH, 409,
                                  "Period has a posted batch")
    period["status"] = "OPEN"
    period["locked_at"] = None
    db.touch(period)
    return object_response(serialize.pay_period(period))


@bp.route("/pay-periods/<pay_period_id>/run-payday", methods=["POST"])
def run_payday(pay_period_id):
    _, role = authenticate()
    require_role(role, {"PayrollOfficer"})
    period = db.pay_periods.get(pay_period_id)
    if period is None:
        raise errors.not_found()
    if period["status"] != "LOCKED":
        raise errors.invalid_state()

    # Exactly one POSTED batch (PRD §3.8, validation: ERR_NO_POSTED_BATCH).
    posted = [
        b for b in db.repayment_batches.values()
        if b["pay_period_id"] == pay_period_id and b["status"] == "POSTED"
    ]
    if len(posted) != 1:
        raise errors.ApiError(errors.ERR_NO_POSTED_BATCH, 409,
                              "Exactly one POSTED batch is required")

    employer = db.employers.get(period["employer_id"])
    if _frozen(employer):
        raise errors.ApiError(errors.ERR_EMPLOYER_FROZEN, 409, "Employer is frozen")

    # Transition + four-hop cascade (PRD §3.8).
    period["status"] = "DISBURSED"
    period["disbursed_at"] = format_iso8601(clock.now())
    db.touch(period)

    # Hop 1: default un-recouped advances.
    affected_workers = set()
    for a in domain.period_advances(pay_period_id):
        if a["status"] in ("DISBURSED", "RECOUPING") and a.get("principal_outstanding_cents", 0) > 0:
            a["status"] = "DEFAULTED"
            db.touch(a)
            affected_workers.add(a["worker_id"])

    # Hop 2: each defaulted advance's worker -> ON_HOLD.
    for wid in affected_workers:
        worker = db.workers.get(wid)
        if worker is not None:
            domain.refresh_worker_eligibility(worker)

    # The POSTED batch becomes RECONCILED.
    posted[0]["status"] = "RECONCILED"
    db.touch(posted[0])

    # Hop 3: recompute the period's reconciliation statement (create if absent).
    domain.recompute_period_statement(pay_period_id, create_if_absent=True)

    # Hop 4: recompute posture (DISCREPANCY -> FROZEN). refresh_employer derives
    # posture from the now-DISBURSED period's statement outcome.
    domain.refresh_employer(employer)

    return object_response(serialize.pay_period(period))
