"""Quoting desk: composition, issue, reprice and conversion
(PRD Sections 3.3, 3.4 and 3.5)."""
from flask import Blueprint, g

import clock
import constants as C
import db
import listing
import response
import serializers as ser
import validation as v
import calculations as calc
from errors import ApiError
from middleware import endpoint, require_owns_customer
from services import lookup, pricing

bp = Blueprint("quotes", __name__)


@bp.post("/quotes")
@endpoint(["SalesRep"])
def create_quote():
    body = v.body()
    customer_id = v.req_str(body, "customer_id")
    branch_id = v.req_str(body, "branch_id")

    # Body foreign keys resolve in declaration order: branch_id, then customer_id.
    lookup.branch(branch_id)
    lookup.customer(customer_id)

    rec = db.base_record()
    rec.update({
        "customer_id": customer_id,
        "branch_id": branch_id,
        "copper_index_entry_id": None,
        "created_by_user_id": g.user_id,
        "issued_by_user_id": None,
        "status": "DRAFT",
        "issued_at": None,
        "valid_until": None,
        "void_reason": None,
        "line_subtotal_cents": 0,
        "physical_reel_count": 0,
        "gross_freight_cents": 0,
        "rebate_pct": 0,
        "rebate_cents": 0,
        "freight_cents": 0,
        "quoted_total_cents": 0,
        "deposit_quoted_cents": 0,
    })
    db.quotes.add(rec)
    return response.object_response(ser.quote(rec), 201)


@bp.get("/quotes/<quote_id>")
@endpoint(["PlatformAdmin", "SalesRep", "Customer"])
def get_quote(quote_id):
    quote = lookup.quote(quote_id)
    require_owns_customer(quote["customer_id"])
    return response.object_response(ser.quote(quote))


@bp.get("/quotes")
@endpoint(["PlatformAdmin", "SalesRep", "Customer"])
def list_quotes():
    v.pagination()
    customer_id = v.query_str("customer_id")
    branch_id = v.query_str("branch_id")
    entry_id = v.query_str("copper_index_entry_id")
    status = v.query_enum("status", C.QUOTE_STATUSES)

    rows = db.quotes.values_ordered()
    if customer_id:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if branch_id:
        rows = [r for r in rows if r["branch_id"] == branch_id]
    if entry_id:
        rows = [r for r in rows if r["copper_index_entry_id"] == entry_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return listing.respond(rows, ser.quote)


@bp.post("/quotes/<quote_id>/lines")
@endpoint(["SalesRep"])
def create_quote_line(quote_id):
    body = v.body()
    product_id = v.req_str(body, "product_id")
    put_up = v.req_enum(body, "put_up", C.PUT_UPS)
    requested_length_ft = v.req_num(body, "requested_length_ft", exclusive_min=0)
    parallel_set_size = v.opt_int(body, "parallel_set_size", 1, minimum=1, maximum=4)
    expected_quote_version = v.req_int(body, "expected_quote_version")

    quote = lookup.quote(quote_id)
    product = lookup.product(product_id)

    if quote["status"] != "DRAFT":
        raise ApiError("ERR_QUOTE_NOT_DRAFT")

    if put_up == "CUT" and calc.dec(requested_length_ft) < C.ABSOLUTE_MIN_CUT_FT:
        raise ApiError("ERR_BELOW_ABSOLUTE_MIN_CUT")

    if put_up not in product["allowed_put_ups"]:
        raise ApiError("ERR_PUT_UP_NOT_ALLOWED")

    if expected_quote_version != quote["version"]:
        raise ApiError("ERR_STALE_QUOTE_VERSION")

    basis = pricing.line_basis(product, put_up, requested_length_ft, parallel_set_size)

    rec = db.base_record()
    rec.update({
        "quote_id": quote_id,
        "product_id": product_id,
        "line_number": len(lookup.quote_lines_of(quote_id)) + 1,
        "put_up": put_up,
        "requested_length_ft": requested_length_ft,
        "parallel_set_size": parallel_set_size,
        "billable_length_ft": basis["billable_length_ft"],
        "reel_count": basis["reel_count"],
        "copper_adder_cents_per_ft": 0,
        "metal_cents": 0,
        "base_cents": 0,
        "cut_charge_cents_total": basis["cut_charge_cents_total"],
        "deposit_cents_total": basis["deposit_cents_total"],
        "quoted_extended_cents": 0,
    })
    db.quote_lines.add(rec)
    db.touch(quote)
    return response.object_response(ser.quote_line(rec), 201)


@bp.get("/quote-lines/<quote_line_id>")
@endpoint(["PlatformAdmin", "SalesRep", "Customer"])
def get_quote_line(quote_line_id):
    return response.object_response(ser.quote_line(lookup.quote_line(quote_line_id)))


@bp.get("/quote-lines")
@endpoint(["PlatformAdmin", "SalesRep", "Customer"])
def list_quote_lines():
    v.pagination()
    quote_id = v.query_str("quote_id")
    product_id = v.query_str("product_id")

    rows = db.quote_lines.values_ordered()
    if quote_id:
        rows = [r for r in rows if r["quote_id"] == quote_id]
    if product_id:
        rows = [r for r in rows if r["product_id"] == product_id]
    if quote_id:
        rows = sorted(rows, key=lambda r: r["line_number"])
    return listing.respond(rows, ser.quote_line)


@bp.post("/quotes/<quote_id>/issue")
@endpoint(["SalesRep"])
def issue_quote(quote_id):
    v.body()
    quote = lookup.quote(quote_id)

    if quote["status"] != "DRAFT":
        raise ApiError("ERR_QUOTE_NOT_DRAFT")

    lines = lookup.quote_lines_of(quote_id)
    if not lines:
        raise ApiError("ERR_QUOTE_HAS_NO_LINES")

    now = clock.now()
    index_entry = lookup.index_entry_on_or_before(clock.date_of(now))
    if index_entry is None:
        raise ApiError("ERR_NO_COPPER_INDEX")

    computed, rollup = pricing.price_quote(quote, index_entry)

    # Segregation of duties is judged on the subtotal computed by THIS request.
    if rollup["line_subtotal_cents"] >= C.SOD_REVIEW_THRESHOLD_CENTS \
            and g.user_id == quote["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    pricing.apply_quote_pricing(quote, index_entry, computed, rollup)
    quote["status"] = "ISSUED"
    quote["issued_at"] = clock.iso(now)
    quote["valid_until"] = clock.iso(calc.valid_until(now))
    quote["issued_by_user_id"] = g.user_id
    db.touch(quote)
    return response.object_response(ser.quote(quote))


@bp.post("/quotes/<quote_id>/reprice")
@endpoint(["SalesRep"])
def reprice_quote(quote_id):
    v.body()
    quote = lookup.quote(quote_id)
    if quote["status"] != "ISSUED":
        raise ApiError("ERR_QUOTE_NOT_ISSUED")

    pricing.clear_quote_pricing(quote)
    quote["status"] = "DRAFT"
    db.touch(quote)
    return response.object_response(ser.quote(quote))


@bp.post("/quotes/<quote_id>/convert")
@endpoint(["SalesRep"])
def convert_quote(quote_id):
    v.body()
    quote = lookup.quote(quote_id)

    if quote["status"] != "ISSUED":
        raise ApiError("ERR_QUOTE_NOT_ISSUED")

    now = clock.now()
    valid_until = clock.parse_dt(quote["valid_until"])
    if valid_until is not None and now > valid_until:
        quote["status"] = "EXPIRED"
        db.touch(quote)
        raise ApiError("ERR_QUOTE_EXPIRED")

    customer = db.customers.get(quote["customer_id"])
    if customer is None:
        raise ApiError("ERR_CUSTOMER_NOT_FOUND")
    if customer["credit_status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_CREDIT_HOLD")
    if calc.available_credit_cents(customer) < quote["quoted_total_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED")

    order = db.base_record()
    order.update({
        "quote_id": quote["id"],
        "customer_id": quote["customer_id"],
        "branch_id": quote["branch_id"],
        "fulfillment_status": "PENDING_ALLOCATION",
        "billing_status": "UNBILLED",
        "allocation_policy": "MINIMIZE_REMNANT",
        "line_subtotal_cents": quote["line_subtotal_cents"],
        "freight_cents": quote["freight_cents"],
        "rebate_cents": quote["rebate_cents"],
        "quoted_total_cents": quote["quoted_total_cents"],
        "invoiced_total_cents": None,
        "metal_variance_cents": None,
        "deposit_charged_cents": 0,
        "deposit_credited_cents": 0,
        "delivered_at": None,
    })
    db.sales_orders.add(order)

    for line in lookup.quote_lines_of(quote["id"]):
        order_line = db.base_record()
        order_line.update({
            "sales_order_id": order["id"],
            "product_id": line["product_id"],
            "line_number": line["line_number"],
            "put_up": line["put_up"],
            "requested_length_ft": line["requested_length_ft"],
            "parallel_set_size": line["parallel_set_size"],
            "billable_length_ft": line["billable_length_ft"],
            "required_length_ft": calc.as_number(
                calc.dec(line["billable_length_ft"]) * calc.dec(line["parallel_set_size"])
            ),
            "allocated_length_ft": 0,
            "allocation_status": "UNALLOCATED",
            "lot_code": None,
            "returnable": line["put_up"] == "MASTER_REEL",
            "quoted_extended_cents": line["quoted_extended_cents"],
            "invoiced_extended_cents": None,
        })
        db.order_lines.add(order_line)

    quote["status"] = "CONVERTED"
    db.touch(quote)
    return response.object_response(ser.sales_order(order), 201)
