"""Settlement lifecycle endpoints (PRD section 3.9)."""
from flask import Blueprint, request

from common import (ApiError, require_role, get_body, ok, ok_list, pagination,
                    created_order, paged, req_str, req_int, opt_int, req_dt,
                    ERR_STALE)
from store import store, init_common, touch
import services as svc
from routes_fleet import ALL, get_driver_or_404

bp = Blueprint("money", __name__)


def get_settlement_or_404(st_id):
    s = store.settlements.get(st_id)
    if s is None:
        raise ApiError("ERR_SETTLEMENT_NOT_FOUND", 404,
                       "Settlement id does not exist")
    return s


@bp.post("/settlements")
def create_settlement():
    uid, _role = require_role(["PayrollClerk"])
    b = get_body()
    driver_id = req_str(b, "driver_id")
    period_start = req_dt(b, "period_start")
    period_end = req_dt(b, "period_end")
    if period_end <= period_start:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "period_end must be strictly after period_start")
    get_driver_or_404(driver_id)
    for s in store.settlements.values():
        if s["driver_id"] != driver_id:
            continue
        # Half-open periods: touching boundaries do not overlap.
        if period_start < s["period_end"] and s["period_start"] < period_end:
            raise ApiError("ERR_SETTLEMENT_PERIOD_OVERLAP", 422,
                           "Period overlaps an existing settlement for this driver")
    st = init_common({
        "driver_id": driver_id,
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "trip_pay_cents": 0,
        "accessorial_share_cents": 0,
        "manual_adjustment_cents": 0,
        "guarantee_top_up_cents": 0,
        "gross_pay_cents": 0,
        "created_by_id": uid,
        "approved_by_id": None,
    })
    svc.compute_settlement_components(st)
    store.settlements[st["id"]] = st
    return ok(st, 201)


@bp.get("/settlements")
def list_settlements():
    require_role(ALL)
    limit, offset = pagination()
    items = list(store.settlements.values())
    driver_id = request.args.get("driver_id")
    status = request.args.get("status")
    if driver_id:
        items = [s for s in items if s["driver_id"] == driver_id]
    if status:
        items = [s for s in items if s["status"] == status]
    items = created_order(items)
    page, total = paged(items, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/settlements/<st_id>")
def get_settlement(st_id):
    require_role(ALL)
    return ok(get_settlement_or_404(st_id))


@bp.post("/settlements/<st_id>/recalculate")
def recalculate_settlement(st_id):
    require_role(["PayrollClerk"])
    s = get_settlement_or_404(st_id)
    b = get_body()
    if "expected_settlement_version" not in b:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field 'expected_settlement_version' is required")
    expected = req_int(b, "expected_settlement_version")
    adjustment = opt_int(b, "manual_adjustment_cents")
    if s["status"] != "DRAFT":
        raise ApiError("ERR_SETTLEMENT_NOT_DRAFT", 409,
                       "Recalculate requires settlement status DRAFT")
    if expected != s["version"]:
        raise ApiError(ERR_STALE, 412,
                       "expected_settlement_version does not match the current Settlement version")
    s["manual_adjustment_cents"] = adjustment if adjustment is not None else 0
    svc.compute_settlement_components(s)
    touch(s)
    return ok(s)


@bp.post("/settlements/<st_id>/submit")
def submit_settlement(st_id):
    require_role(["PayrollClerk"])
    s = get_settlement_or_404(st_id)
    if s["status"] != "DRAFT":
        raise ApiError("ERR_SETTLEMENT_NOT_DRAFT", 409,
                       "Submit requires settlement status DRAFT")
    s["status"] = "PENDING_APPROVAL"
    touch(s)
    return ok(s)


@bp.post("/settlements/<st_id>/reject")
def reject_settlement(st_id):
    require_role(["PayrollClerk"])
    s = get_settlement_or_404(st_id)
    if s["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_SETTLEMENT_NOT_PENDING_APPROVAL", 409,
                       "Reject requires settlement status PENDING_APPROVAL")
    s["status"] = "DRAFT"
    touch(s)
    return ok(s)


@bp.post("/settlements/<st_id>/approve")
def approve_settlement(st_id):
    uid, _role = require_role(["PayrollClerk"])
    s = get_settlement_or_404(st_id)
    if s["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_SETTLEMENT_NOT_PENDING_APPROVAL", 409,
                       "Approve requires settlement status PENDING_APPROVAL")
    if uid == s["created_by_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTY", 403,
                       "Settlement approver must differ from its creator")
    s["approved_by_id"] = uid
    s["status"] = "APPROVED"
    touch(s)
    return ok(s)


@bp.post("/settlements/<st_id>/mark-paid")
def mark_settlement_paid(st_id):
    require_role(["PayrollClerk"])
    s = get_settlement_or_404(st_id)
    if s["status"] != "APPROVED":
        raise ApiError("ERR_SETTLEMENT_NOT_APPROVED", 409,
                       "Mark-paid requires settlement status APPROVED")
    s["status"] = "PAID"
    touch(s)
    return ok(s)
