"""Quote and quote line item endpoints."""
from decimal import Decimal
from flask import Blueprint, request

from core import (
    db, ApiError, body, ok_object, paginate, new_record, touch, serialize,
    require_roles, get_case_or_404, get_child_or_404, require_case_active,
    check_expected_case_version, req_str, req_enum, req_dt, req_int, req_num,
    opt_num, opt_bool, opt_int, now, now_iso, iso,
)
from domain import (
    mutate_case, advance_case_funding, compute_quote_totals, quote_line_amounts,
    make_quote_number, release_pending_allocations_for_quote, commit_allocation,
    run_funding_waterfall, waterfall_capacity,
)

bp = Blueprint("quotes", __name__)

LINE_TYPES = ("LABOR", "MATERIAL", "PERMIT", "EQUIPMENT_RENTAL",
              "EQUIPMENT_PURCHASE", "DEMOLITION", "ELECTRICAL", "PLUMBING")


def _get_quote(case_id, quote_id):
    case = get_case_or_404(case_id)
    quote = get_child_or_404("quotes", quote_id, "case_id", case_id,
                             "ERR_QUOTE_NOT_FOUND", "Quote")
    return case, quote


@bp.route("/cases/<caseId>/quotes", methods=["POST"])
def create_quote(caseId):
    require_roles("ProjectManager")
    case = get_case_or_404(caseId)
    if case["status"] in ("CLOSED", "CANCELLED"):
        raise ApiError("ERR_CASE_NOT_ACTIVE", 409,
                       "Case must be in an active state (not CANCELLED or CLOSED)")
    if case["status"] in ("INTAKE", "ASSESSMENT_SCHEDULED"):
        raise ApiError("ERR_CASE_NOT_ASSESSED", 409,
                       "Case must be ASSESSED before creating quotes")
    b = body()
    check_expected_case_version(case, b)
    valid_until = req_dt(b, "valid_until")
    contingency = opt_num(b, "contingency_pct", Decimal("10.0"))
    if contingency < 0 or contingency > Decimal("25.0"):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "contingency_pct must be between 0 and 25.0")
    discount = opt_int(b, "discount_cents", 0)

    # Revision: increment over existing quotes for this case; supersede open ones.
    existing = [q for q in db["quotes"].values() if q["case_id"] == caseId]
    revision = len(existing) + 1

    rec = new_record()
    rec.update({
        "case_id": caseId,
        "quote_number": make_quote_number(),
        "revision": revision,
        "status": "DRAFT",
        "valid_until": iso(valid_until),
        "labor_cost_cents": 0,
        "material_cost_cents": 0,
        "permit_fee_cents": 0,
        "equipment_cost_cents": 0,
        "contingency_pct": float(contingency),
        "contingency_cents": 0,
        "subtotal_cents": 0,
        "discount_cents": discount,
        "total_cents": 0,
        "funding_gap_cents": None,
        "superseded_by_id": None,
        "submitted_at": None,
        "decided_at": None,
        "_valid_until_dt": valid_until,
    })
    db["quotes"][rec["id"]] = rec

    for q in existing:
        if q["status"] in ("DRAFT", "SUBMITTED", "UNDER_REVIEW"):
            q["status"] = "SUPERSEDED"
            q["superseded_by_id"] = rec["id"]
            touch(q)
            release_pending_allocations_for_quote(q["id"])

    if case["status"] == "ASSESSED":
        case["status"] = "QUOTE_DRAFTED"
    mutate_case(case)
    return ok_object(serialize(rec), 201)


@bp.route("/cases/<caseId>/quotes", methods=["GET"])
def list_quotes(caseId):
    require_roles()
    get_case_or_404(caseId)
    status = request.args.get("status")
    records = [q for q in db["quotes"].values() if q["case_id"] == caseId]
    if status is not None:
        records = [q for q in records if q["status"] == status]
    return paginate(records)


@bp.route("/cases/<caseId>/quotes/<quoteId>", methods=["GET"])
def get_quote(caseId, quoteId):
    require_roles()
    _case, quote = _get_quote(caseId, quoteId)
    return ok_object(serialize(quote))


@bp.route("/cases/<caseId>/quotes/<quoteId>/line-items", methods=["POST"])
def add_line_item(caseId, quoteId):
    require_roles("ProjectManager")
    case, quote = _get_quote(caseId, quoteId)
    require_case_active(case)
    if quote["status"] != "DRAFT":
        raise ApiError("ERR_QUOTE_NOT_DRAFT", 409,
                       "Quote must be DRAFT to add line items")
    b = body()
    line_type = req_enum(b, "line_type", LINE_TYPES)
    description = req_str(b, "description")
    quantity = req_num(b, "quantity")
    unit = req_str(b, "unit")
    unit_price = req_int(b, "unit_price_cents")
    sort_order = req_int(b, "sort_order")
    is_taxable = opt_bool(b, "is_taxable", True)
    tax_rate = opt_num(b, "tax_rate_pct", Decimal("0.0"))
    funding_eligible = opt_bool(b, "funding_eligible", True)
    if quantity <= 0 or unit_price <= 0:
        raise ApiError("ERR_INVALID_LINE_ITEM", 422,
                       "Line item has invalid quantity or price")

    ext, tax = quote_line_amounts(quantity, unit_price, is_taxable, tax_rate)
    rec = new_record()
    rec.update({
        "quote_id": quoteId,
        "line_type": line_type,
        "description": description,
        "quantity": float(quantity),
        "unit": unit,
        "unit_price_cents": unit_price,
        "extended_price_cents": ext,
        "is_taxable": is_taxable,
        "tax_rate_pct": float(tax_rate),
        "tax_cents": tax,
        "funding_eligible": funding_eligible,
        "sort_order": sort_order,
    })
    db["quote_line_items"][rec["id"]] = rec
    compute_quote_totals(quote)
    touch(quote)
    mutate_case(case)
    return ok_object(serialize(rec), 201)


@bp.route("/cases/<caseId>/quotes/<quoteId>/submit", methods=["POST"])
def submit_quote(caseId, quoteId):
    require_roles("ProjectManager")
    case, quote = _get_quote(caseId, quoteId)
    require_case_active(case)
    if quote["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Quote must be DRAFT to submit")
    lines = [li for li in db["quote_line_items"].values()
             if li["quote_id"] == quoteId]
    if not lines:
        raise ApiError("ERR_QUOTE_EMPTY", 422, "Quote has no line items")
    if not (quote["_valid_until_dt"] > now()):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Quote validity period has passed")

    compute_quote_totals(quote)
    quote["status"] = "SUBMITTED"
    quote["submitted_at"] = now_iso()
    quote["funding_gap_cents"] = max(
        0, quote["total_cents"] - case["total_funded_cents"])
    touch(quote)

    if case["status"] == "QUOTE_DRAFTED":
        case["status"] = "QUOTE_SUBMITTED"
    mutate_case(case)
    advance_case_funding(case)
    touch(case)
    return ok_object(serialize(quote))


@bp.route("/cases/<caseId>/quotes/<quoteId>/start-review", methods=["POST"])
def start_review(caseId, quoteId):
    require_roles("FundingCoordinator")
    case, quote = _get_quote(caseId, quoteId)
    require_case_active(case)
    if quote["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Quote must be SUBMITTED to start review")
    quote["status"] = "UNDER_REVIEW"
    touch(quote)
    return ok_object(serialize(quote))


@bp.route("/cases/<caseId>/quotes/<quoteId>/approve", methods=["POST"])
def approve_quote(caseId, quoteId):
    require_roles("FundingCoordinator")
    case, quote = _get_quote(caseId, quoteId)
    require_case_active(case)
    if quote["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Quote must be UNDER_REVIEW to approve")

    compute_quote_totals(quote)
    need = quote["total_cents"]
    pending = [a for a in db["funding_allocations"].values()
               if a["quote_id"] == quoteId and a["status"] == "PENDING"]
    pending_sum = sum(a["amount_cents"] for a in pending)
    # Validate each pending allocation still fits its source's remaining balance.
    for a in pending:
        src = db["funding_sources"].get(a["funding_source_id"])
        if src is None or src["status"] not in ("APPROVED",) or \
                (src.get("remaining_cents") or 0) < a["amount_cents"]:
            raise ApiError("ERR_INSUFFICIENT_FUNDING", 402,
                           "Approved funding is insufficient for quote total")
    residual = max(0, need - pending_sum)
    if residual > 0:
        capacity = waterfall_capacity(case, quote, residual)
        if capacity < residual:
            raise ApiError("ERR_INSUFFICIENT_FUNDING", 402,
                           "Approved funding is insufficient for quote total")

    # Commit: existing pending allocations, then waterfall for the residual.
    for a in pending:
        src = db["funding_sources"][a["funding_source_id"]]
        commit_allocation(a, src)
    if residual > 0:
        run_funding_waterfall(case, quote, residual)

    quote["status"] = "APPROVED"
    quote["decided_at"] = now_iso()
    touch(quote)
    mutate_case(case)
    advance_case_funding(case)
    touch(case)
    return ok_object(serialize(quote))


@bp.route("/cases/<caseId>/quotes/<quoteId>/reject", methods=["POST"])
def reject_quote(caseId, quoteId):
    require_roles("FundingCoordinator")
    case, quote = _get_quote(caseId, quoteId)
    require_case_active(case)
    if quote["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Quote must be UNDER_REVIEW to reject")
    quote["status"] = "REJECTED"
    quote["decided_at"] = now_iso()
    touch(quote)
    release_pending_allocations_for_quote(quoteId)
    mutate_case(case)
    return ok_object(serialize(quote))
