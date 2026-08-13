"""WriteDownRequest endpoints (PRD §3.6)."""
from flask import Blueprint

import db
import util
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_MATTER_NOT_OPEN,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_WRITE_DOWN_ENTRIES_INVALID,
    ERR_WRITE_DOWN_ENTRY_STATE,
    ERR_WRITE_DOWN_AMOUNT_INVALID,
    ERR_FORBIDDEN_FOR_ROLE,
)
from middleware import get_context, require_roles
from response import success_object, success_list
from services import derived

bp = Blueprint("write_downs", __name__)

REASON_CODES = {"CLIENT_RELATIONS", "BILLING_ERROR", "SCOPE_DISPUTE", "COLLECTIBILITY", "COURT_ORDER"}
READ_ROLES = ("FirmAdmin", "PricingAnalyst", "BillingPartner", "ManagingPartner")

# Firm-wide authority threshold (PRD §2.8 names the constant without a value).
PARTNER_WRITE_DOWN_AUTHORITY_CENTS = 100000


def _resolve_entries(wdr):
    """Return list of (entry_or_none) for the request's time_entry_ids."""
    return [db.time_entries.get(eid) for eid in wdr.get("time_entry_ids", [])]


def _validate_entries_exist_and_owned(wdr):
    entries = _resolve_entries(wdr)
    for e in entries:
        if e is None or e.get("matter_id") != wdr.get("matter_id"):
            raise ApiError(ERR_WRITE_DOWN_ENTRIES_INVALID,
                           "time_entry_ids missing or do not belong to matter", 422)
    return entries


def _validate_amount(wdr, entries):
    total = sum(int(e.get("billable_amount_cents", 0)) for e in entries)
    amount = int(wdr.get("requested_amount_cents", 0))
    if amount <= 0 or amount > total:
        raise ApiError(ERR_WRITE_DOWN_AMOUNT_INVALID,
                       "Requested write-down amount <= 0 or > sum of entry amounts", 422)


@bp.post("/firms/<firmId>/matters/<matterId>/write_down_requests")
def create_write_down(firmId, matterId):
    ctx = get_context()
    require_roles(ctx, "BillingPartner")
    util.get_firm(firmId)
    matter = util.get_matter_scoped(firmId, matterId)
    data = util.body()
    util.require_fields(data, ["time_entry_ids", "requested_amount_cents", "reason_code"])

    ids = data.get("time_entry_ids")
    if not isinstance(ids, list) or not ids:
        raise ApiError(ERR_WRITE_DOWN_ENTRIES_INVALID,
                       "time_entry_ids must be a non-empty array", 422)
    for eid in ids:
        if not isinstance(eid, str):
            raise ApiError(ERR_WRITE_DOWN_ENTRIES_INVALID,
                           "time_entry_ids must contain string ids", 422)
    amount = util.check_int(data, "requested_amount_cents")
    reason = util.check_enum(data, "reason_code", REASON_CODES)

    wdr = util.new_resource()
    wdr.update({
        "matter_id": matter["id"],
        "firm_id": firmId,
        "time_entry_ids": list(ids),
        "requested_amount_cents": amount,
        "approved_amount_cents": None,
        "reason_code": reason,
        "requested_by_user_id": ctx.user_id,
        "decided_by_user_id": None,
        "decided_period_index": None,
        "status": "DRAFT",
    })

    # Creation-time validation battery (PRD §3.6).
    entries = _validate_entries_exist_and_owned(wdr)
    for e in entries:
        if e.get("status") not in ("APPROVED", "BILLED"):
            raise ApiError(ERR_WRITE_DOWN_ENTRIES_INVALID,
                           "One or more entries not in APPROVED/BILLED state", 422)
    _validate_amount(wdr, entries)

    db.write_down_requests[wdr["id"]] = wdr
    return success_object(wdr, 201)


@bp.get("/firms/write_down_requests/<requestId>")
def get_write_down(requestId):
    ctx = get_context()
    require_roles(ctx, *READ_ROLES)
    wdr = util.get_write_down_flat(requestId)
    return success_object(wdr, 200)


@bp.get("/firms/write_down_requests")
def list_write_downs():
    ctx = get_context()
    require_roles(ctx, *READ_ROLES)
    filters = util.query_filters(["firm_id", "matter_id", "status"])
    items = util.apply_filters(list(db.write_down_requests.values()), filters)
    window, meta = util.paginate(items)
    return success_list(window, meta, 200)


@bp.get("/firms/matters/<matterId>/write_down_requests")
def list_write_downs_for_matter(matterId):
    ctx = get_context()
    require_roles(ctx, *READ_ROLES)
    matter = util.get_matter_flat(matterId)
    filters = util.query_filters(["status"])
    items = [w for w in db.write_down_requests.values() if w.get("matter_id") == matter["id"]]
    items = util.apply_filters(items, filters)
    window, meta = util.paginate(items)
    return success_list(window, meta, 200)


@bp.post("/firms/<firmId>/write_down_requests/<requestId>/submit")
def submit_write_down(firmId, requestId):
    ctx = get_context()
    require_roles(ctx, "BillingPartner")
    wdr = util.get_write_down_scoped(firmId, requestId)
    if wdr["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only a DRAFT write-down request can be submitted", 409)

    # Re-validation battery (PRD §3.6): existence/ownership, state, amount.
    entries = _validate_entries_exist_and_owned(wdr)
    for e in entries:
        if e.get("status") not in ("APPROVED", "BILLED"):
            raise ApiError(ERR_WRITE_DOWN_ENTRY_STATE,
                           "One or more entries not in APPROVED/BILLED state", 422)
    _validate_amount(wdr, entries)

    if int(wdr["requested_amount_cents"]) <= PARTNER_WRITE_DOWN_AUTHORITY_CENTS:
        wdr["status"] = "PENDING_PARTNER"
    else:
        wdr["status"] = "PENDING_MANAGING_PARTNER"
    util.touch(wdr)
    return success_object(wdr, 200)


@bp.post("/firms/<firmId>/write_down_requests/<requestId>/decide")
def decide_write_down(firmId, requestId):
    ctx = get_context()
    require_roles(ctx, "BillingPartner", "ManagingPartner")
    firm = util.get_firm(firmId)
    wdr = util.get_write_down_scoped(firmId, requestId)

    if wdr["status"] == "PENDING_PARTNER":
        require_roles(ctx, "BillingPartner")
    elif wdr["status"] == "PENDING_MANAGING_PARTNER":
        require_roles(ctx, "ManagingPartner")
    else:
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Write-down request is not awaiting a decision", 409)

    data = util.body()
    decision = data.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        raise ApiError(ERR_INVALID_REQUEST, "decision must be APPROVE or REJECT", 400)

    # Segregation of duties (§2.8) before anything else about the decision.
    if ctx.user_id == wdr.get("requested_by_user_id"):
        raise ApiError(ERR_SEGREGATION_OF_DUTIES,
                       "Same user cannot request and decide", 409)

    wdr["decided_by_user_id"] = ctx.user_id
    if decision == "APPROVE":
        wdr["status"] = "APPROVED"
        wdr["approved_amount_cents"] = int(wdr["requested_amount_cents"])
        wdr["decided_period_index"] = int(firm.get("current_period_index", 0))
    else:
        wdr["status"] = "REJECTED"
        wdr["decided_period_index"] = int(firm.get("current_period_index", 0))
    util.touch(wdr)
    return success_object(wdr, 200)


@bp.post("/firms/<firmId>/write_down_requests/<requestId>/apply")
def apply_write_down(firmId, requestId):
    ctx = get_context()
    require_roles(ctx, "BillingPartner", "ManagingPartner")
    firm = util.get_firm(firmId)
    wdr = util.get_write_down_scoped(firmId, requestId)
    if wdr["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only an APPROVED write-down request can be applied", 409)
    matter = db.matters.get(wdr["matter_id"])
    if matter is None:
        from errors import err_not_found
        raise err_not_found("Matter not found")
    if matter["status"] not in ("ACTIVE", "REOPENED"):
        raise ApiError(ERR_MATTER_NOT_OPEN,
                       "Matter not in ACTIVE/REOPENED for write-down apply", 409)

    entries = _validate_entries_exist_and_owned(wdr)
    approved = int(wdr.get("approved_amount_cents") or 0)
    total = sum(int(e.get("billable_amount_cents", 0)) for e in entries)
    if total <= 0:
        raise ApiError(ERR_WRITE_DOWN_AMOUNT_INVALID,
                       "Sum of entry amounts is zero", 422)

    # Waterfall allocation (PRD §3.6): floor per entry, leftover one cent at a
    # time in created_at ASC order.
    for e in entries:
        raw = approved * int(e.get("billable_amount_cents", 0)) // total
        e["_alloc"] = raw
    leftover = approved - sum(e["_alloc"] for e in entries)
    for e in sorted(entries, key=util.order_key):
        if leftover <= 0:
            break
        e["_alloc"] += 1
        leftover -= 1

    for e in entries:
        e["written_down_amount_cents"] = int(e.get("written_down_amount_cents", 0)) + e["_alloc"]
        e["status"] = "WRITTEN_DOWN"
        del e["_alloc"]
        util.touch(e)

    wdr["status"] = "APPLIED"
    util.touch(wdr)

    derived.recompute_phase_actuals(matter["id"])
    derived.recompute_matter(matter)
    matter["last_activity_period_index"] = int(firm.get("current_period_index", 0))
    util.touch(matter)
    return success_object(wdr, 200)


@bp.post("/firms/<firmId>/write_down_requests/<requestId>/cancel")
def cancel_write_down(firmId, requestId):
    ctx = get_context()
    require_roles(ctx, "BillingPartner")
    wdr = util.get_write_down_scoped(firmId, requestId)
    if wdr["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Only a DRAFT write-down request can be cancelled", 409)
    if ctx.user_id != wdr.get("requested_by_user_id"):
        raise ApiError(ERR_FORBIDDEN_FOR_ROLE,
                       "Only the requesting user may cancel a draft write-down", 403)
    wdr["status"] = "CANCELLED"
    util.touch(wdr)
    return success_object(wdr, 200)
