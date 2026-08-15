"""BoxOrder endpoints."""
import math
from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import (
    err_board_source_mismatch,
    err_ect_spec_not_met,
    err_grade_discontinued,
    err_invalid_request,
    err_invalid_state,
    err_not_found,
    err_supplier_required,
)
from middleware import require_roles
from response import success_object
from services.calcs import (
    bump,
    compute_area_sqft_per_box,
    compute_pricing,
    recompute_credit_exposure,
    recompute_run_trim,
    recompute_shift_rollup,
)
from services.serialize import serialize_box_order, serialize_price_quote, serialize_quality_claim
from util import D, is_int, is_num, new_id, utcnow_iso
from ._helpers import get_json_body, paginate_list, require_fields

bp = Blueprint("box_orders", __name__)

ALL_ROLES = ("PlantAdmin", "SalesRep", "ProductionPlanner", "CustomerService", "ClaimsAdjuster", "Customer")
ROUTING_TYPES = {"DIE_CUT", "SLOTTED"}
BOARD_SOURCES = {"INTERNAL", "SHEET_FEEDER"}

CANCELLABLE_STATES = {"DRAFT", "QUOTED", "ACCEPTED", "SCHEDULED", "AWAITING_CONVERTING", "DIE_CUT_QUEUED", "SLOTTED_QUEUED"}


def _get_order_or_404(oid):
    o = db.box_orders.get(oid)
    if o is None:
        raise err_not_found("box order not found")
    return o


@bp.route("/api/box-orders", methods=["POST"])
@require_roles("SalesRep")
def create_box_order(_user_id, _role):
    body = get_json_body()
    require_fields(body, [
        "customer_id", "board_grade_id", "routing_type", "board_source",
        "quantity", "blank_width_in", "blank_length_in", "min_ect_required",
    ])

    customer_id = body["customer_id"]
    board_grade_id = body["board_grade_id"]
    routing_type = body["routing_type"]
    board_source = body["board_source"]
    sheet_supplier_name = body.get("sheet_supplier_name")
    quantity = body["quantity"]
    blank_width = body["blank_width_in"]
    blank_length = body["blank_length_in"]
    min_ect = body["min_ect_required"]
    ink_colors = body.get("ink_colors", [])

    # Well-formedness first (priority 6 ERR_INVALID_REQUEST)
    if routing_type not in ROUTING_TYPES:
        raise err_invalid_request("routing_type must be DIE_CUT or SLOTTED")
    if board_source not in BOARD_SOURCES:
        raise err_invalid_request("board_source must be INTERNAL or SHEET_FEEDER")
    if not is_int(quantity) or quantity <= 0:
        raise err_invalid_request("quantity must be an integer > 0")
    if not is_num(blank_width) or D(blank_width) <= 0:
        raise err_invalid_request("blank_width_in must be > 0")
    if not is_num(blank_length) or D(blank_length) <= 0:
        raise err_invalid_request("blank_length_in must be > 0")
    if not is_int(min_ect) or min_ect < 0:
        raise err_invalid_request("min_ect_required must be an integer >= 0")
    if not isinstance(ink_colors, list):
        raise err_invalid_request("ink_colors must be an array")
    for c in ink_colors:
        if not isinstance(c, str):
            raise err_invalid_request("ink_colors entries must be strings")

    # Existence (priority 3) — FKs resolve
    cust = db.customer_accounts.get(customer_id)
    if cust is None:
        raise err_not_found("customer not found")
    grade = db.board_grades.get(board_grade_id)
    if grade is None:
        raise err_not_found("board grade not found")

    # ECT floor (priority 5)
    if min_ect > grade["ect_rating_lbs_per_in"]:
        raise err_ect_spec_not_met("min_ect_required exceeds grade ect_rating_lbs_per_in")

    # Supplier rule (priority 6)
    if board_source == "SHEET_FEEDER":
        if not isinstance(sheet_supplier_name, str) or not sheet_supplier_name.strip():
            raise err_supplier_required("SHEET_FEEDER order requires sheet_supplier_name")
    else:  # INTERNAL
        if sheet_supplier_name is not None:
            raise err_supplier_required("INTERNAL order forbids sheet_supplier_name")

    # Grade ACTIVE at order creation (priority 7)
    if grade["status"] != "ACTIVE":
        raise err_grade_discontinued("referenced board grade is DISCONTINUED")

    now = utcnow_iso()
    oid = new_id()
    area = compute_area_sqft_per_box(blank_width, blank_length)
    order = {
        "id": oid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "customer_id": customer_id,
        "board_grade_id": board_grade_id,
        "routing_type": routing_type,
        "board_source": board_source,
        "sheet_supplier_name": sheet_supplier_name if board_source == "SHEET_FEEDER" else None,
        "quantity": quantity,
        "blank_width_in": D(blank_width),
        "blank_length_in": D(blank_length),
        "min_ect_required": min_ect,
        "ink_colors": list(ink_colors),
        "color_count": len(ink_colors),
        "corrugator_run_id": None,
        "area_sqft_per_box": area,
        "committed_value_dollars": Decimal("0.00"),
        "produced_qty": None,
        "invoice_billable_msf": None,
        "invoice_merchandise_dollars": None,
        "invoice_discount_dollars": None,
        "invoice_freight_dollars": None,
        "invoice_total_dollars": None,
        "status": "DRAFT",
    }
    db.box_orders[oid] = order
    return success_object(serialize_box_order(order), 201)


@bp.route("/api/box-orders/<oid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_box_order(oid, _user_id, _role):
    o = _get_order_or_404(oid)
    return success_object(serialize_box_order(o), 200)


@bp.route("/api/box-orders", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_box_orders(_user_id, _role):
    filters = {
        "customer_id": request.args.get("customer_id"),
        "board_grade_id": request.args.get("board_grade_id"),
        "corrugator_run_id": request.args.get("corrugator_run_id"),
        "status": request.args.get("status"),
    }
    return paginate_list(list(db.box_orders.values()), serialize_box_order, filters)


@bp.route("/api/box-orders/<oid>/cancel", methods=["POST"])
@require_roles("SalesRep")
def cancel_box_order(oid, _user_id, _role):
    o = _get_order_or_404(oid)
    if o["status"] not in CANCELLABLE_STATES:
        raise err_invalid_state(f"order in status {o['status']} cannot be cancelled")

    prior_status = o["status"]

    # Supersede OPEN quotes (ACCEPTED quote unchanged)
    for q in db.price_quotes.values():
        if q["order_id"] == o["id"] and q["status"] == "OPEN":
            q["status"] = "SUPERSEDED"
            bump(q)

    # Detach from corrugator run if SCHEDULED
    if prior_status == "SCHEDULED" and o.get("corrugator_run_id"):
        run_id = o["corrugator_run_id"]
        run = db.corrugator_runs.get(run_id)
        o["corrugator_run_id"] = None
        # Drop outs bookkeeping
        if run_id in db.run_outs:
            db.run_outs[run_id].pop(o["id"], None)
        if run is not None:
            recompute_run_trim(run)
            bump(run)

    # Cancel QUEUED booking if DIE_CUT_QUEUED or SLOTTED_QUEUED
    if prior_status in ("DIE_CUT_QUEUED", "SLOTTED_QUEUED"):
        for b in db.converting_bookings.values():
            if b["box_order_id"] == o["id"] and b["status"] == "QUEUED":
                b["status"] = "CANCELLED"
                bump(b)
                shift = db.work_shifts.get(b["work_shift_id"])
                if shift is not None:
                    recompute_shift_rollup(shift)
                    bump(shift)
                break

    o["status"] = "CANCELLED"
    bump(o)

    cust = db.customer_accounts.get(o["customer_id"])
    if cust is not None:
        recompute_credit_exposure(cust)
        bump(cust)

    return success_object(serialize_box_order(o), 200)


@bp.route("/api/box-orders/<oid>/mark-sheets-received", methods=["POST"])
@require_roles("ProductionPlanner")
def mark_sheets_received(oid, _user_id, _role):
    o = _get_order_or_404(oid)
    if o["status"] != "ACCEPTED":
        raise err_invalid_state("order is not ACCEPTED")
    if o["board_source"] != "SHEET_FEEDER":
        raise err_board_source_mismatch("mark-sheets-received applies only to SHEET_FEEDER orders")
    o["status"] = "AWAITING_CONVERTING"
    bump(o)
    return success_object(serialize_box_order(o), 200)


@bp.route("/api/box-orders/<oid>/invoice", methods=["POST"])
@require_roles("SalesRep")
def invoice_box_order(oid, _user_id, _role):
    o = _get_order_or_404(oid)
    if o["status"] != "PRODUCED":
        raise err_invalid_state("order is not PRODUCED")

    # Locate the ACCEPTED quote
    accepted = None
    for q in db.price_quotes.values():
        if q["order_id"] == o["id"] and q["status"] == "ACCEPTED":
            accepted = q
            break
    if accepted is None:
        # Should not happen for a PRODUCED order; treat as state error
        raise err_invalid_state("no ACCEPTED quote found for order")

    cust = db.customer_accounts.get(o["customer_id"])
    if cust is None:
        raise err_not_found("customer not found")

    # FINAL variant pricing using produced_qty and locked unit_price
    pr = compute_pricing(o, cust, o["produced_qty"], accepted["unit_price_per_msf"])
    o["invoice_billable_msf"] = pr["billable_msf"]
    o["invoice_merchandise_dollars"] = pr["merchandise_total_dollars"]
    o["invoice_discount_dollars"] = pr["discount_dollars"]
    o["invoice_freight_dollars"] = pr["freight_charge_dollars"]
    o["invoice_total_dollars"] = pr["grand_total_dollars"]

    # ACCEPTED quote -> INVOICED
    accepted["status"] = "INVOICED"
    bump(accepted)

    o["status"] = "INVOICED"
    bump(o)

    recompute_credit_exposure(cust)
    bump(cust)

    return success_object(serialize_box_order(o), 200)


# =============================================================================
# Quotes on an order
# =============================================================================

@bp.route("/api/box-orders/<oid>/quotes", methods=["POST"])
@require_roles("SalesRep")
def create_quote(oid, _user_id, _role):
    from services.clock import get_logical_clock
    from errors import err_stale_version

    o = _get_order_or_404(oid)
    body = get_json_body()
    require_fields(body, ["unit_price_per_msf", "expires_on", "expected_order_version"])

    unit_price = body["unit_price_per_msf"]
    expires_on = body["expires_on"]
    expected_version = body["expected_order_version"]

    # Well-formedness
    if not is_num(unit_price) or D(unit_price) <= 0:
        raise err_invalid_request("unit_price_per_msf must be > 0")
    if not isinstance(expires_on, str):
        raise err_invalid_request("expires_on must be an ISO date string")
    from util import parse_date
    if parse_date(expires_on) is None:
        raise err_invalid_request("expires_on must be a valid ISO date (YYYY-MM-DD)")
    if not is_int(expected_version):
        raise err_invalid_request("expected_order_version must be an integer")

    # State check: order DRAFT or QUOTED
    if o["status"] not in ("DRAFT", "QUOTED"):
        raise err_invalid_state(f"order status {o['status']} does not allow quoting")

    # OCC check
    if expected_version != o["version"]:
        raise err_stale_version()

    # Customer lookup
    cust = db.customer_accounts.get(o["customer_id"])
    if cust is None:
        raise err_not_found("customer not found")

    # Supersede every other OPEN quote on this order
    for q in db.price_quotes.values():
        if q["order_id"] == o["id"] and q["status"] == "OPEN":
            q["status"] = "SUPERSEDED"
            bump(q)

    # PROVISIONAL pricing
    pr = compute_pricing(o, cust, o["quantity"], unit_price)

    now = utcnow_iso()
    qid = new_id()
    quote = {
        "id": qid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "order_id": o["id"],
        "unit_price_per_msf": D(unit_price),
        "expires_on": expires_on,
        "billable_msf": pr["billable_msf"],
        "freight_tier": pr["freight_tier"],
        "merchandise_total_dollars": pr["merchandise_total_dollars"],
        "discount_pct": pr["discount_pct"],
        "discount_dollars": pr["discount_dollars"],
        "freight_charge_dollars": pr["freight_charge_dollars"],
        "quote_total_dollars": pr["grand_total_dollars"],
        "status": "OPEN",
    }
    db.price_quotes[qid] = quote

    # Order state: DRAFT -> QUOTED or QUOTED -> QUOTED; bump version
    o["status"] = "QUOTED"
    bump(o)

    return success_object(serialize_price_quote(quote), 201)


@bp.route("/api/box-orders/<oid>/quotes", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_quotes_for_order(oid, _user_id, _role):
    o = _get_order_or_404(oid)
    quotes = [q for q in db.price_quotes.values() if q["order_id"] == o["id"]]
    return paginate_list(quotes, serialize_price_quote, {})


@bp.route("/api/box-orders/<oid>/quality-claims", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_claims_for_order(oid, _user_id, _role):
    o = _get_order_or_404(oid)
    claims = [c for c in db.quality_claims.values() if c["box_order_id"] == o["id"]]
    return paginate_list(claims, serialize_quality_claim, {})
