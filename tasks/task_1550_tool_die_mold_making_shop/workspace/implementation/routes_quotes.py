"""Quote endpoints: create (priced), issue, respond (PRD §3.3)."""
from datetime import timedelta

from flask import Blueprint, request

from store import STORE, now
from helpers import (ApiError, endpoint, get_body, validate_payload, ok, created,
                     ok_list, paginate, filter_eq, sort_created, not_found,
                     stamp_new, bump)
from domain import (ser_quote, price_quote, QUOTE_KINDS, WARRANTY_TERMS,
                    MIN_LEAD_WEEKS, VALIDITY_DAYS, customer_outstanding_cents)

bp = Blueprint("quotes", __name__)


@bp.route("/quotes", methods=["POST"])
@endpoint(roles=["Estimator"])
def create_quote(uid, role):
    data = validate_payload(get_body(), [
        ("customer_id", "str", True),
        ("tool_design_id", "str", True),
        ("quote_kind", "enum", True, {"values": QUOTE_KINDS}),
        ("requested_lead_weeks", "int", True, {"min": 1}),
        ("expedited", "bool", False),
        ("warranty_terms", "enum", False, {"values": WARRANTY_TERMS}),
        ("expected_tool_design_version", "int", True),
    ])
    # Tier 4: body FK existence, customer_id before tool_design_id.
    cust = STORE.customers.get(data["customer_id"])
    if cust is None:
        not_found("CUSTOMER")
    design = STORE.designs.get(data["tool_design_id"])
    if design is None:
        not_found("TOOL_DESIGN")
    # Tier 6: OCC against the design version.
    if data["expected_tool_design_version"] != design["version"]:
        raise ApiError("ERR_STALE_TOOL_DESIGN_VERSION", 412,
                       "The tool design version has advanced since it was observed")
    # Tier 10: lead-time feasibility against the class minimum (boundary allowed).
    if data["requested_lead_weeks"] < MIN_LEAD_WEEKS[design["die_class"]]:
        raise ApiError("ERR_LEAD_TIME_INFEASIBLE", 422,
                       "requested_lead_weeks is below the class minimum")
    # Tier 11: customer must be ACTIVE.
    if cust["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED", 409,
                       "Customer is suspended for credit aging")
    kind = data["quote_kind"]
    priced = price_quote(design, kind, data["requested_lead_weeks"],
                         data.get("expedited", False))
    quote = stamp_new({
        "customer_id": data["customer_id"],
        "tool_design_id": data["tool_design_id"],
        "quote_kind": kind,
        "requested_lead_weeks": data["requested_lead_weeks"],
        "expedited": data.get("expedited", False),
        "warranty_terms": data.get("warranty_terms", "LINEAR_PRORATION"),
        "base_price_cents": priced["base_price_cents"],
        "surcharge_pct": priced["surcharge_pct"],
        "subtotal_cents": priced["subtotal_cents"],
        "contingency_pct": priced["contingency_pct"],
        "total_price_cents": priced["total_price_cents"],
        "issued_at": None,
        "valid_until": None,
        "status": "DRAFT",
    })
    STORE.quotes[quote["id"]] = quote
    # Quoting feeds back into the design: quoted_count +1 bumps its version.
    design["quoted_count"] += 1
    bump(design)
    return created(ser_quote(quote))


@bp.route("/quotes", methods=["GET"])
@endpoint(roles=None)
def list_quotes(uid, role):
    items = sort_created(list(STORE.quotes.values()))
    items = filter_eq(items, "customer_id", request.args.get("customer_id"))
    items = filter_eq(items, "tool_design_id", request.args.get("tool_design_id"))
    items = filter_eq(items, "status", request.args.get("status"))
    page, meta = paginate(items)
    return ok_list([ser_quote(q) for q in page], meta)


@bp.route("/quotes/<quoteId>", methods=["GET"])
@endpoint(roles=None)
def get_quote(uid, role, quoteId):
    quote = STORE.quotes.get(quoteId)
    if quote is None:
        not_found("QUOTE")
    return ok(ser_quote(quote))


@bp.route("/quotes/<quoteId>/issue", methods=["POST"])
@endpoint(roles=["Estimator"])
def issue_quote(uid, role, quoteId):
    validate_payload(get_body(), [])
    quote = STORE.quotes.get(quoteId)
    if quote is None:
        not_found("QUOTE")
    if quote["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a DRAFT quote may be issued")
    design = STORE.designs.get(quote["tool_design_id"])
    if quote["quote_kind"] == "FIRM":
        if design is None or design["status"] != "RELEASED":
            raise ApiError("ERR_DESIGN_NOT_RELEASED", 409,
                           "A FIRM quote requires a RELEASED design")
    else:
        if design is None or design["status"] not in ("SUBMITTED", "RELEASED"):
            raise ApiError("ERR_DESIGN_NOT_RELEASED", 409,
                           "A BUDGETARY quote requires a SUBMITTED or RELEASED design")
    issued_at = now()
    quote["issued_at"] = issued_at
    quote["valid_until"] = issued_at + timedelta(days=VALIDITY_DAYS[quote["quote_kind"]])
    # Supersede cascade: every other ISSUED quote for this design.
    for other in STORE.quotes.values():
        if (other["id"] != quote["id"]
                and other["tool_design_id"] == quote["tool_design_id"]
                and other["status"] == "ISSUED"):
            other["status"] = "SUPERSEDED"
            bump(other)
    quote["status"] = "ISSUED"
    bump(quote)
    return ok(ser_quote(quote))


@bp.route("/quotes/<quoteId>/respond", methods=["POST"])
@endpoint(roles=["Customer"])
def respond_quote(uid, role, quoteId):
    data = validate_payload(get_body(), [
        ("decision", "enum", True, {"values": {"ACCEPTED", "DECLINED"}}),
    ])
    quote = STORE.quotes.get(quoteId)
    if quote is None:
        not_found("QUOTE")
    # Tier 5: ownership.
    if quote["customer_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                       "Only the quote's customer may respond")
    # Tier 7: state.
    if quote["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an ISSUED quote may be answered")
    # Tier 9: expiry — lazily transitions ISSUED -> EXPIRED and the call fails.
    if now() > quote["valid_until"]:
        quote["status"] = "EXPIRED"
        bump(quote)
        raise ApiError("ERR_QUOTE_EXPIRED", 409, "The quote validity window has passed")
    if data["decision"] == "DECLINED":
        quote["status"] = "DECLINED"
        bump(quote)
        return ok(ser_quote(quote))
    # ACCEPTED: tier 11 customer-active gate, then tier 12 credit gate.
    cust = STORE.customers.get(quote["customer_id"])
    if cust is None or cust["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED", 409,
                       "Customer is suspended for credit aging")
    limit = cust["credit_limit_cents"]
    if limit != 0 and customer_outstanding_cents(cust["id"]) + quote["total_price_cents"] > limit:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 402,
                       "Accepting this quote would exceed the customer's credit limit")
    quote["status"] = "ACCEPTED"
    bump(quote)
    return ok(ser_quote(quote))
