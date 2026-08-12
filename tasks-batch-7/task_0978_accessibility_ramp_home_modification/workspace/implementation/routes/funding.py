"""Funding source and allocation endpoints."""
from flask import Blueprint

from core import (
    db, ApiError, body, ok_object, paginate, new_record, touch, serialize,
    require_roles, get_case_or_404, get_child_or_404, require_case_active,
    check_expected_case_version, req_str, req_enum, req_int, opt_str, opt_dt,
    opt_array, now_iso, iso,
)
from domain import (
    mutate_case, advance_case_funding, release_pending_allocations_for_source,
    source_has_rental_restriction, RENTAL_LINE_TYPES,
)

bp = Blueprint("funding", __name__)

SOURCE_TYPES = ("MEDICAID_WAIVER", "VA_BENEFIT", "STATE_GRANT",
                "PRIVATE_INSURANCE", "SELF_PAY", "CHARITY")
ALLOCATION_TYPES = ("QUOTE_LEVEL", "LINE_LEVEL")


def _get_source(case_id, source_id):
    case = get_case_or_404(case_id)
    src = get_child_or_404("funding_sources", source_id, "case_id", case_id,
                           "ERR_FUNDING_SOURCE_NOT_FOUND", "Funding source")
    return case, src


@bp.route("/cases/<caseId>/funding-sources", methods=["POST"])
def create_funding_source(caseId):
    require_roles("FundingCoordinator")
    case = get_case_or_404(caseId)
    require_case_active(case)
    b = body()
    rec = new_record()
    rec.update({
        "case_id": caseId,
        "source_type": req_enum(b, "source_type", SOURCE_TYPES),
        "program_name": req_str(b, "program_name"),
        "application_number": opt_str(b, "application_number"),
        "status": "PENDING",
        "requested_cents": req_int(b, "requested_cents"),
        "approved_cents": None,
        "remaining_cents": None,
        "decision_date": None,
        "expiration_date": iso(opt_dt(b, "expiration_date")),
        "priority_rank": req_int(b, "priority_rank"),
        "restrictions": opt_array(b, "restrictions", []),
    })
    db["funding_sources"][rec["id"]] = rec
    advance_case_funding(case)
    touch(case)
    return ok_object(serialize(rec), 201)


@bp.route("/cases/<caseId>/funding-sources", methods=["GET"])
def list_funding_sources(caseId):
    require_roles()
    get_case_or_404(caseId)
    records = [s for s in db["funding_sources"].values() if s["case_id"] == caseId]
    return paginate(records)


@bp.route("/cases/<caseId>/funding-sources/<sourceId>", methods=["GET"])
def get_funding_source(caseId, sourceId):
    require_roles()
    _case, src = _get_source(caseId, sourceId)
    return ok_object(serialize(src))


@bp.route("/cases/<caseId>/funding-sources/<sourceId>/approve", methods=["POST"])
def approve_funding_source(caseId, sourceId):
    require_roles("FundingCoordinator")
    case, src = _get_source(caseId, sourceId)
    require_case_active(case)
    if src["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Funding source must be PENDING to approve")
    b = body()
    approved = b.get("approved_cents")
    d = None
    from core import _to_decimal
    if approved is not None:
        d = _to_decimal(approved)
    if d is None or d != d.to_integral_value() or int(d) <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Missing or invalid required field: approved_cents")
    check_expected_case_version(case, b)

    src["status"] = "APPROVED"
    src["approved_cents"] = int(d)
    src["remaining_cents"] = int(d)
    src["decision_date"] = now_iso()
    touch(src)
    mutate_case(case)
    advance_case_funding(case)
    touch(case)
    return ok_object(serialize(src))


@bp.route("/cases/<caseId>/funding-sources/<sourceId>/deny", methods=["POST"])
def deny_funding_source(caseId, sourceId):
    require_roles("FundingCoordinator")
    case, src = _get_source(caseId, sourceId)
    require_case_active(case)
    if src["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Funding source must be PENDING to deny")
    src["status"] = "DENIED"
    src["decision_date"] = now_iso()
    touch(src)
    mutate_case(case)
    return ok_object(serialize(src))


@bp.route("/cases/<caseId>/funding-sources/<sourceId>/withdraw", methods=["POST"])
def withdraw_funding_source(caseId, sourceId):
    require_roles("FundingCoordinator")
    case, src = _get_source(caseId, sourceId)
    require_case_active(case)
    if src["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Funding source must be PENDING to withdraw")
    src["status"] = "WITHDRAWN"
    touch(src)
    release_pending_allocations_for_source(sourceId)
    mutate_case(case)
    return ok_object(serialize(src))


@bp.route("/cases/<caseId>/funding-sources/<sourceId>/allocations", methods=["POST"])
def create_allocation(caseId, sourceId):
    require_roles("FundingCoordinator")
    case, src = _get_source(caseId, sourceId)
    require_case_active(case)
    b = body()
    quote_id = req_str(b, "quote_id")
    quote = db["quotes"].get(quote_id)
    if quote is None or quote["case_id"] != caseId:
        raise ApiError("ERR_QUOTE_NOT_FOUND", 404,
                       "Quote with given ID does not exist")
    amount = req_int(b, "amount_cents")
    alloc_type = req_enum(b, "allocation_type", ALLOCATION_TYPES)
    line_item_id = b.get("quote_line_item_id")
    line_item = None
    if alloc_type == "LINE_LEVEL":
        if not line_item_id:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "Missing or invalid required field: quote_line_item_id")
        line_item = db["quote_line_items"].get(line_item_id)
        if line_item is None or line_item["quote_id"] != quote_id:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "quote_line_item_id does not reference a line on the quote")
    elif line_item_id is not None:
        line_item = db["quote_line_items"].get(line_item_id)
        if line_item is None or line_item["quote_id"] != quote_id:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "quote_line_item_id does not reference a line on the quote")

    # (9) Restriction check before (10) balance check.
    if source_has_rental_restriction(src):
        if line_item is not None and line_item["line_type"] in RENTAL_LINE_TYPES:
            raise ApiError("ERR_FUNDING_RESTRICTION_VIOLATION", 422,
                           "Funding source restrictions prohibit this allocation")
        if line_item is None:
            has_rental = any(
                li["line_type"] in RENTAL_LINE_TYPES
                for li in db["quote_line_items"].values()
                if li["quote_id"] == quote_id)
            if has_rental:
                raise ApiError("ERR_FUNDING_RESTRICTION_VIOLATION", 422,
                               "Funding source restrictions prohibit this allocation")
    remaining = src.get("remaining_cents")
    if remaining is None:
        remaining = 0
    if amount > remaining:
        raise ApiError("ERR_ALLOCATION_EXCEEDS_REMAINING", 422,
                       "Allocation amount exceeds funding source remaining balance")

    rec = new_record()
    rec.update({
        "funding_source_id": sourceId,
        "quote_id": quote_id,
        "quote_line_item_id": line_item_id,
        "amount_cents": amount,
        "allocation_type": alloc_type,
        "status": "PENDING",
        "committed_at": None,
    })
    db["funding_allocations"][rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/cases/<caseId>/funding-sources/<sourceId>/allocations", methods=["GET"])
def list_allocations(caseId, sourceId):
    require_roles()
    _case, src = _get_source(caseId, sourceId)
    records = [a for a in db["funding_allocations"].values()
               if a["funding_source_id"] == sourceId]
    return paginate(records)


@bp.route("/cases/<caseId>/funding-sources/<sourceId>/allocations/<allocId>/reverse",
          methods=["POST"])
def reverse_allocation(caseId, sourceId, allocId):
    require_roles("FundingCoordinator")
    case, src = _get_source(caseId, sourceId)
    require_case_active(case)
    alloc = get_child_or_404("funding_allocations", allocId, "funding_source_id",
                             sourceId, "ERR_FUNDING_SOURCE_NOT_FOUND",
                             "Funding allocation")
    if alloc["status"] != "COMMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Allocation must be COMMITTED to reverse")
    paid_invoice = any(
        i for i in db["invoices"].values()
        if i["case_id"] == caseId
        and i.get("funding_source_id") == sourceId
        and i["amount_paid_cents"] > 0)
    if paid_invoice:
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "An invoice has been paid against this funding source")

    alloc["status"] = "REVERSED"
    touch(alloc)
    src["remaining_cents"] = (src.get("remaining_cents") or 0) + alloc["amount_cents"]
    touch(src)
    mutate_case(case)
    return ok_object(serialize(alloc))
