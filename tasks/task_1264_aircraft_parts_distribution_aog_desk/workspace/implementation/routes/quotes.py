"""Quote endpoints: draft, list, get, issue, accept, reject, revise, cancel."""

from datetime import timedelta

from flask import Blueprint, request

from auth import require_roles, forbid_unless_owner, ALL_BUSINESS
from calc import TIER_CAPS
from db import store, clock
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_CUSTOMER_NOT_FOUND, ERR_PART_NOT_FOUND,
                    ERR_AOG_REQUEST_NOT_FOUND, ERR_QUOTE_NOT_FOUND,
                    ERR_CUSTOMER_SUSPENDED, ERR_VALIDITY_EXCEEDS_TIER_CAP,
                    ERR_QUOTE_EXPIRED, ERR_STALE_QUOTE_VERSION,
                    ERR_CREDIT_LIMIT_EXCEEDED, ERR_DUPLICATE_ACTIVE_QUOTE)
from helpers import (new_record, touch, get_or_404, ser_quote, sort_asc,
                     effective_quote_status, recompute_quote,
                     quote_core_deposits)
from util import (success, get_body, page_params, paged, req_present, as_str,
                  as_int, as_num, as_enum, as_list, fmt_dt, rhu, bad)
from decimal import Decimal

bp = Blueprint("quotes", __name__)

SALE_TYPES = {"OUTRIGHT", "EXCHANGE", "LOAN", "LEASE"}
CONDITIONS = {"NEW", "OVERHAULED", "SERVICEABLE", "AS_REMOVED"}
FREIGHT_MODES = {"STANDARD", "HOT_SHOT", "CHARTER"}


def _validate_lines(raw_lines):
    """Shape + per-line business-shape validation. Returns normalized lines."""
    lines = as_list(raw_lines, "lines")
    if not lines:
        bad("lines must be a non-empty array")
    out = []
    for ln in lines:
        if not isinstance(ln, dict):
            bad("each line must be an object")
        part_id = as_str(req_present(ln, "part_id"), "lines[].part_id")
        quantity = as_int(req_present(ln, "quantity"), "lines[].quantity")
        if quantity < 1:
            bad("line quantity must be >= 1")
        sale_type = as_enum(req_present(ln, "sale_type"), "lines[].sale_type",
                            SALE_TYPES)
        unit_price = as_int(req_present(ln, "unit_price_cents"),
                            "lines[].unit_price_cents")
        if unit_price < 0:
            bad("line unit_price_cents must be >= 0")
        discount = as_num(req_present(ln, "discount_pct"),
                          "lines[].discount_pct")
        if not (0 <= discount < 1):
            bad("line discount_pct must be in [0, 1)")
        condition = as_enum(req_present(ln, "condition_required"),
                            "lines[].condition_required", CONDITIONS)
        lease_periods = ln.get("lease_periods")
        if sale_type == "LEASE":
            lease_periods = as_int(
                req_present(ln, "lease_periods"), "lines[].lease_periods")
            if lease_periods < 1:
                bad("lease_periods must be >= 1")
        elif lease_periods is not None:
            bad("lease_periods is only allowed on LEASE lines")
        part = store["parts"].get(part_id)
        if part is None:
            raise ApiError(ERR_PART_NOT_FOUND, 404,
                           f"PartMaster not found: {part_id}")
        if sale_type in ("EXCHANGE", "LOAN", "LEASE") and not part["rotable"]:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           f"{sale_type} line targets a non-rotable part")
        if sale_type in ("LOAN", "LEASE") and quantity != 1:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "LOAN/LEASE lines must have quantity 1")
        out.append({
            "part_id": part_id,
            "quantity": quantity,
            "sale_type": sale_type,
            "unit_price_cents": unit_price,
            "discount_pct": discount,
            "condition_required": condition,
            "lease_periods": lease_periods if sale_type == "LEASE" else None,
        })
    return out


def _validate_common(body, partial=False):
    """Validate quote scalar fields. Returns dict of provided values."""
    vals = {}
    if not partial or "validity_hours" in body:
        v = as_int(req_present(body, "validity_hours"), "validity_hours")
        if v < 1:
            bad("validity_hours must be >= 1")
        vals["validity_hours"] = v
    if not partial or "distance_km" in body:
        v = as_int(req_present(body, "distance_km"), "distance_km")
        if v < 1:
            bad("distance_km must be >= 1")
        vals["distance_km"] = v
    if not partial or "chargeable_weight_kg" in body:
        v = as_int(req_present(body, "chargeable_weight_kg"),
                   "chargeable_weight_kg")
        if v < 1:
            bad("chargeable_weight_kg must be >= 1")
        vals["chargeable_weight_kg"] = v
    if not partial or "destination_country" in body:
        vals["destination_country"] = as_str(
            req_present(body, "destination_country"), "destination_country")
    if "freight_mode" in body and body["freight_mode"] is not None:
        vals["freight_mode"] = as_enum(body["freight_mode"], "freight_mode",
                                       FREIGHT_MODES)
    elif not partial:
        vals["freight_mode"] = "STANDARD"
    return vals


@bp.post("/aog/quotes")
def create_quote():
    require_roles("AogDeskAgent")
    body = get_body()
    req_id = as_str(req_present(body, "aog_request_id"), "aog_request_id")
    customer_id = as_str(req_present(body, "customer_id"), "customer_id")
    vals = _validate_common(body)
    aog = get_or_404("requests", req_id, ERR_AOG_REQUEST_NOT_FOUND,
                     "AogRequest")
    customer = get_or_404("customers", customer_id, ERR_CUSTOMER_NOT_FOUND,
                          "Customer")
    if aog["customer_id"] != customer_id:
        bad("customer_id must match the AOG request's customer")
    lines = _validate_lines(req_present(body, "lines"))
    if aog["status"] not in ("OPEN", "QUOTED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "AOG request status does not permit a new quote")
    for q in store["quotes"].values():
        if q["aog_request_id"] == aog["id"] and \
                effective_quote_status(q) in ("DRAFT", "ISSUED"):
            raise ApiError(ERR_DUPLICATE_ACTIVE_QUOTE, 409,
                           "AogRequest already has a DRAFT or ISSUED quote")
    rec = new_record("quotes", {
        "aog_request_id": aog["id"],
        "customer_id": customer["id"],
        "lines": lines,
        "validity_hours": vals["validity_hours"],
        "freight_mode": vals["freight_mode"],
        "distance_km": vals["distance_km"],
        "chargeable_weight_kg": vals["chargeable_weight_kg"],
        "destination_country": vals["destination_country"],
        "revision_count": 0,
        "status": "DRAFT",
        "tier_at_issue": None,
        "issued_at": None,
        "expires_at": None,
        "_issued_dt": None,
        "_expires_dt": None,
        "subtotal_cents": 0,
        "handling_fee_cents": 0,
        "tier_fee_cents": 0,
        "freight_cost_cents": 0,
        "total_cents": 0,
        "max_penalty_cents": 0,
    })
    recompute_quote(rec)
    return success(ser_quote(rec), 201)


@bp.get("/aog/quotes")
def list_quotes():
    uid, role = require_roles(*ALL_BUSINESS)
    limit, offset = page_params()
    recs = list(store["quotes"].values())
    if role == "CustomerContact":
        recs = [q for q in recs if q["customer_id"] == uid]
    q = request.args
    if q.get("customer_id") is not None:
        recs = [x for x in recs if x["customer_id"] == q.get("customer_id")]
    if q.get("status") is not None:
        recs = [x for x in recs if x["status"] == q.get("status")]
    if q.get("aog_request_id") is not None:
        recs = [x for x in recs if x["aog_request_id"] == q.get("aog_request_id")]
    return paged([ser_quote(x) for x in sort_asc(recs)], limit, offset)


@bp.get("/aog/quotes/<qid>")
def get_quote(qid):
    require_roles(*ALL_BUSINESS)
    rec = get_or_404("quotes", qid, ERR_QUOTE_NOT_FOUND, "Quote")
    return success(ser_quote(rec))


@bp.post("/aog/quotes/<qid>/issue")
def issue_quote(qid):
    require_roles("AogDeskAgent")
    quote = get_or_404("quotes", qid, ERR_QUOTE_NOT_FOUND, "Quote")
    if quote["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a DRAFT quote can be issued")
    customer = store["customers"][quote["customer_id"]]
    if customer["status"] != "ACTIVE":
        raise ApiError(ERR_CUSTOMER_SUSPENDED, 409,
                       "Customer is suspended")
    tier = customer["priority_tier"]
    if quote["validity_hours"] > TIER_CAPS[tier]:
        raise ApiError(ERR_VALIDITY_EXCEEDS_TIER_CAP, 422,
                       "validity_hours exceeds the tier cap")
    issued = clock.current
    quote["tier_at_issue"] = tier
    quote["_issued_dt"] = issued
    quote["issued_at"] = fmt_dt(issued)
    quote["_expires_dt"] = issued + timedelta(hours=quote["validity_hours"])
    quote["expires_at"] = fmt_dt(quote["_expires_dt"])
    quote["status"] = "ISSUED"
    recompute_quote(quote)
    touch(quote)
    aog = store["requests"].get(quote["aog_request_id"])
    if aog is not None and aog["status"] == "OPEN":
        aog["status"] = "QUOTED"
        touch(aog)
    return success(ser_quote(quote))


@bp.post("/aog/quotes/<qid>/accept")
def accept_quote(qid):
    uid, role = require_roles("CustomerContact")
    quote = get_or_404("quotes", qid, ERR_QUOTE_NOT_FOUND, "Quote")
    forbid_unless_owner(role, uid, quote["customer_id"])
    status = effective_quote_status(quote)
    if status == "EXPIRED":
        raise ApiError(ERR_QUOTE_EXPIRED, 409, "Quote has expired")
    if status != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an ISSUED quote can be accepted")
    customer = store["customers"][quote["customer_id"]]
    if customer["status"] != "ACTIVE":
        raise ApiError(ERR_CUSTOMER_SUSPENDED, 409, "Customer is suspended")
    body = get_body()
    if "expected_quote_version" not in body or \
            body["expected_quote_version"] is None:
        bad("expected_quote_version is required")
    expected = as_int(body["expected_quote_version"],
                      "expected_quote_version")
    if expected != quote["version"]:
        raise ApiError(ERR_STALE_QUOTE_VERSION, 412,
                       "expected_quote_version does not match current quote "
                       "version")
    exposure = (customer["outstanding_balance_cents"] + quote["total_cents"]
                + quote_core_deposits(quote))
    if exposure > customer["credit_limit_cents"]:
        raise ApiError(ERR_CREDIT_LIMIT_EXCEEDED, 402,
                       "Credit exposure exceeds the credit limit")
    # --- acceptance cascade (atomic) ---
    order = new_record("orders", {
        "quote_id": quote["id"],
        "customer_id": quote["customer_id"],
        "fulfillment_status": "PENDING_ALLOCATION",
        "compliance_status": "PENDING_SCREENING",
        "payment_status": "UNBILLED",
        "invoiced_cents": 0,
        "freight_mode": quote["freight_mode"],
        "distance_km": quote["distance_km"],
        "chargeable_weight_kg": quote["chargeable_weight_kg"],
        "destination_country": quote["destination_country"],
    })
    for ln in quote["lines"]:
        for _ in range(ln["quantity"]):
            per_unit = rhu(Decimal(ln["unit_price_cents"])
                           * (Decimal(1) - Decimal(str(ln["discount_pct"]))))
            new_record("order_lines", {
                "order_id": order["id"],
                "part_id": ln["part_id"],
                "quantity": 1,
                "sale_type": ln["sale_type"],
                "condition_required": ln["condition_required"],
                "unit_price_cents": ln["unit_price_cents"],
                "discount_pct": ln["discount_pct"],
                "line_total_cents": per_unit,
                "lease_periods": ln["lease_periods"],
                "allocated_unit_id": None,
                "allocation_status": "PENDING",
                "delivered_at": None,
                "_delivered_dt": None,
            })
    aog = store["requests"].get(quote["aog_request_id"])
    if aog is not None and aog["status"] == "QUOTED":
        aog["status"] = "FULFILLING"
        touch(aog)
    quote["status"] = "ACCEPTED"
    touch(quote)
    return success(ser_quote(quote))


@bp.post("/aog/quotes/<qid>/reject")
def reject_quote(qid):
    uid, role = require_roles("CustomerContact")
    quote = get_or_404("quotes", qid, ERR_QUOTE_NOT_FOUND, "Quote")
    forbid_unless_owner(role, uid, quote["customer_id"])
    if effective_quote_status(quote) != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an ISSUED quote can be rejected")
    quote["status"] = "REJECTED"
    touch(quote)
    return success(ser_quote(quote))


@bp.post("/aog/quotes/<qid>/revise")
def revise_quote(qid):
    require_roles("AogDeskAgent")
    quote = get_or_404("quotes", qid, ERR_QUOTE_NOT_FOUND, "Quote")
    status = effective_quote_status(quote)
    if status not in ("REJECTED", "EXPIRED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a REJECTED or EXPIRED quote can be revised")
    body = get_body()
    if "expected_quote_version" not in body or \
            body["expected_quote_version"] is None:
        bad("expected_quote_version is required")
    expected = as_int(body["expected_quote_version"],
                      "expected_quote_version")
    if expected != quote["version"]:
        raise ApiError(ERR_STALE_QUOTE_VERSION, 412,
                       "expected_quote_version does not match current quote "
                       "version")
    if "lines" in body and body["lines"] is not None:
        quote["lines"] = _validate_lines(body["lines"])
    vals = _validate_common(body, partial=True)
    for k, v in vals.items():
        quote[k] = v
    quote["revision_count"] = quote.get("revision_count", 0) + 1
    quote["tier_at_issue"] = None
    quote["issued_at"] = None
    quote["expires_at"] = None
    quote["_issued_dt"] = None
    quote["_expires_dt"] = None
    quote["status"] = "DRAFT"
    recompute_quote(quote)
    touch(quote)
    return success(ser_quote(quote))


@bp.post("/aog/quotes/<qid>/cancel")
def cancel_quote(qid):
    require_roles("AogDeskAgent")
    quote = get_or_404("quotes", qid, ERR_QUOTE_NOT_FOUND, "Quote")
    if quote["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a DRAFT quote can be cancelled")
    quote["status"] = "CANCELLED"
    touch(quote)
    return success(ser_quote(quote))
