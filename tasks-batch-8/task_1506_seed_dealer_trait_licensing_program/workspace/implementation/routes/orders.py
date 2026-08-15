"""SeedOrder and OrderLine endpoints, including confirmation pricing,
cancellation, hold release, prepay, and payment recording."""

import db
from errors import (
    ApiError,
    ERR_INVALID_STATE_TRANSITION,
    ERR_PROGRAM_NOT_OPEN,
    ERR_RECOMMENDATION_MISMATCH,
    ERR_ORDER_HAS_NO_LINES,
    ERR_ORDER_HAS_DELIVERIES,
    ERR_GROWER_NOT_ACTIVE,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_PREPAY_WINDOW_CLOSED,
    ERR_PREPAY_AMOUNT_INSUFFICIENT,
    ERR_VARIETY_DELISTED,
    ERR_TREATMENT_INCOMPATIBLE,
)
from middleware import authenticate, check_grower_ownership, GROWER
from response import success_obj, success_list
from routes import make_blueprint
from services import (
    lines_of_order,
    tickets_of_order,
    check_trait_gate,
    early_order_discount_bps,
    compute_order_totals,
    plan_allocation,
    apply_allocation,
    release_line_reservation,
    treatment_adder,
)
from util import body_json, check_shape, pagination_params, paginate, apply_filters, require_fk, exist_body_fks, dt_of, rhu_div

bp = make_blueprint("orders")

ALL_ROLES = ["DealerAdmin", "SalesRep", "Agronomist", "Grower", "ClaimsAdjuster"]


def _order_viewable_grower_check(uid, role, order):
    check_grower_ownership(uid, role, order["grower_id"])


# --- SeedOrder ---------------------------------------------------------------

@bp.post("/orders")
def create_order():
    uid, role = authenticate(["DealerAdmin", "SalesRep", "Grower"])
    body = body_json()
    if role == GROWER and "grower_id" in body:
        check_grower_ownership(uid, role, body["grower_id"])
    exist_body_fks(body, {
        "grower_id": ("growers", "grower"),
        "program_id": ("programs", "program"),
        "recommendation_id": ("recommendations", "recommendation"),
    })
    check_shape(body, {
        "grower_id": {"type": "string", "required": True},
        "program_id": {"type": "string", "required": True},
        "recommendation_id": {"type": "string"},
    })
    rec_id = body.get("recommendation_id")
    if rec_id is not None:
        rec = db.get("recommendations", rec_id)
        if rec["grower_id"] != body["grower_id"] or rec["status"] not in ("PUBLISHED", "ACCEPTED"):
            raise ApiError(ERR_RECOMMENDATION_MISMATCH, 409, "recommendation must belong to the order's grower and be PUBLISHED or ACCEPTED")
    program = db.get("programs", body["program_id"])
    if program["status"] != "OPEN":
        raise ApiError(ERR_PROGRAM_NOT_OPEN, 409, "program is not OPEN")
    order = db.new_entity("orders", {
        "grower_id": body["grower_id"],
        "program_id": body["program_id"],
        "recommendation_id": rec_id,
        "is_replacement": False,
        "status": "DRAFT",
        "payment_status": "UNPAID",
        "fulfillment_status": "NONE",
        "confirmed_at": None,
        "locked_discount_bps": 0,
        "total_units": 0,
        "gross_amount_cents": 0,
        "rebate_bps_applied": 0,
        "rebate_amount_cents": 0,
        "prepay_discount_cents": 0,
        "net_amount_cents": 0,
        "prepaid_amount_cents": 0,
        "paid_amount_cents": 0,
    })
    return success_obj(db.public(order), 201)


@bp.get("/orders/<oid>")
def get_order(oid):
    uid, role = authenticate(ALL_ROLES)
    order = require_fk("orders", oid, "order")
    _order_viewable_grower_check(uid, role, order)
    return success_obj(db.public(order), 200)


@bp.get("/orders")
def list_orders():
    uid, role = authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = db.all_of("orders")
    if role == GROWER:
        items = [o for o in items if o["grower_id"] == uid]
    items = apply_filters(items, ["grower_id", "program_id", "recommendation_id", "status", "payment_status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(o) for o in page], limit, offset, total, has_more)


# --- OrderLine ----------------------------------------------------------------

@bp.post("/orders/<oid>/lines")
def add_order_line(oid):
    uid, role = authenticate(["DealerAdmin", "SalesRep", "Grower"])
    order = require_fk("orders", oid, "order")
    _order_viewable_grower_check(uid, role, order)
    body = body_json()
    exist_body_fks(body, {
        "variety_id": ("varieties", "variety"),
        "treatment_option_id": ("treatment_options", "treatment option"),
    })
    check_shape(body, {
        "variety_id": {"type": "string", "required": True},
        "units": {"type": "integer", "required": True, "min": 1},
        "treatment_option_id": {"type": "string"},
    })
    if order["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "lines may be added only to a DRAFT order")
    variety = db.get("varieties", body["variety_id"])
    # Compliance (priority 9) precedes catalog-availability checks (priority 11).
    check_trait_gate(order["grower_id"], variety)
    if variety["status"] != "LISTED":
        raise ApiError(ERR_VARIETY_DELISTED, 409, "variety is not LISTED")
    topt_id = body.get("treatment_option_id")
    if topt_id is not None:
        topt = db.get("treatment_options", topt_id)
        if topt["status"] != "AVAILABLE" or topt["crop"] != variety["crop"]:
            raise ApiError(ERR_TREATMENT_INCOMPATIBLE, 409, "treatment option is not AVAILABLE or targets a different crop")
    line = db.new_entity("order_lines", {
        "order_id": order["id"],
        "variety_id": body["variety_id"],
        "treatment_option_id": topt_id,
        "units": body["units"],
        "unit_price_cents": variety["base_price_cents_per_unit"],
        "discounted_unit_price_cents": None,
        "line_total_cents": 0,
        "inventory_lot_id": None,
        "reserved_units": 0,
        "delivered_units": 0,
        "returned_units": 0,
    })
    # Pre-confirm estimate: locked discount 0 -> list price + adder, per unit.
    line["line_total_cents"] = (
        line["unit_price_cents"] * line["units"] + treatment_adder(line) * line["units"]
    )
    db.touch(line)
    # Order totals recompute from lines (draft: rebate/prepay remain zero).
    lines = lines_of_order(order["id"])
    order["total_units"] = sum(l["units"] for l in lines)
    order["gross_amount_cents"] = sum(l["line_total_cents"] for l in lines)
    order["net_amount_cents"] = (
        order["gross_amount_cents"] - order["rebate_amount_cents"] - order["prepay_discount_cents"]
    )
    db.touch(order)
    return success_obj(db.public(line), 201)


@bp.get("/order-lines/<lid>")
def get_order_line(lid):
    uid, role = authenticate(ALL_ROLES)
    line = require_fk("order_lines", lid, "order line")
    order = db.get("orders", line["order_id"])
    check_grower_ownership(uid, role, order["grower_id"] if order else None)
    return success_obj(db.public(line), 200)


@bp.get("/order-lines")
def list_order_lines():
    uid, role = authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = db.all_of("order_lines")
    if role == GROWER:
        own_orders = {o["id"] for o in db.all_of("orders") if o["grower_id"] == uid}
        items = [l for l in items if l["order_id"] in own_orders]
    items = apply_filters(items, ["order_id", "variety_id", "treatment_option_id", "inventory_lot_id"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(l) for l in page], limit, offset, total, has_more)


# --- Order actions ------------------------------------------------------------

@bp.post("/orders/<oid>/confirm")
def confirm_order(oid):
    uid, role = authenticate(["SalesRep", "Grower"])
    order = require_fk("orders", oid, "order")
    _order_viewable_grower_check(uid, role, order)
    # Priority 7: state legality.
    if order["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only a DRAFT order can be confirmed")
    program = db.get("programs", order["program_id"])
    if program is None or program["status"] != "OPEN":
        raise ApiError(ERR_PROGRAM_NOT_OPEN, 409, "program is not OPEN")
    lines = lines_of_order(order["id"])
    grower = db.get("growers", order["grower_id"])
    # Priority 9: stewardship gate on every traited line.
    for line in lines:
        variety = db.get("varieties", line["variety_id"])
        if variety is not None:
            check_trait_gate(order["grower_id"], variety)
    # Priority 11: structure then inventory allocation (simulated atomically).
    if not lines:
        raise ApiError(ERR_ORDER_HAS_NO_LINES, 409, "order has no lines")
    total_units = sum(l["units"] for l in lines)
    locked_bps = early_order_discount_bps(order, program, total_units)
    totals = compute_order_totals(order, program, lines, locked_bps)
    allocation = plan_allocation(lines)
    # Priority 12: money checks last.
    if grower is None or grower["status"] != "ACTIVE":
        raise ApiError(ERR_GROWER_NOT_ACTIVE, 409, "grower account is not ACTIVE")
    if grower["outstanding_balance_cents"] + totals["net_amount_cents"] > grower["credit_limit_cents"]:
        raise ApiError(ERR_CREDIT_LIMIT_EXCEEDED, 409, "credit limit exceeded")
    # Commit: pricing lock, totals, reservations.
    order["locked_discount_bps"] = locked_bps
    for line, disc_unit, line_total in totals["plan"]:
        line["discounted_unit_price_cents"] = disc_unit
        line["line_total_cents"] = line_total
        db.touch(line)
    order["total_units"] = totals["total_units"]
    order["gross_amount_cents"] = totals["gross_amount_cents"]
    order["rebate_bps_applied"] = totals["rebate_bps_applied"]
    order["rebate_amount_cents"] = totals["rebate_amount_cents"]
    order["net_amount_cents"] = totals["net_amount_cents"]
    apply_allocation(allocation)
    order["confirmed_at"] = db.fmt_ts(db.now())
    order["status"] = "CONFIRMED"
    db.touch(order)
    return success_obj(db.public(order), 200)


@bp.post("/orders/<oid>/cancel")
def cancel_order(oid):
    uid, role = authenticate(["DealerAdmin", "SalesRep", "Grower"])
    order = require_fk("orders", oid, "order")
    _order_viewable_grower_check(uid, role, order)
    if order["status"] == "DRAFT":
        order["status"] = "CANCELLED"
        db.touch(order)
        return success_obj(db.public(order), 200)
    if order["status"] == "CONFIRMED":
        for ticket in tickets_of_order(order["id"]):
            if ticket["status"] == "COMPLETED":
                raise ApiError(ERR_ORDER_HAS_DELIVERIES, 409, "order has completed deliveries")
        for line in lines_of_order(order["id"]):
            release_line_reservation(line)
        for ticket in tickets_of_order(order["id"]):
            if ticket["status"] == "SCHEDULED":
                ticket["status"] = "CANCELLED"
                db.touch(ticket)
        if order["payment_status"] == "PREPAID":
            order["payment_status"] = "UNPAID"
            order["prepaid_amount_cents"] = 0
            order["prepay_discount_cents"] = 0
            order["net_amount_cents"] = order["gross_amount_cents"] - order["rebate_amount_cents"]
        order["status"] = "CANCELLED"
        db.touch(order)
        return success_obj(db.public(order), 200)
    if order["status"] == "COMPLIANCE_HOLD":
        order["status"] = "CANCELLED"
        db.touch(order)
        return success_obj(db.public(order), 200)
    raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "order cannot be cancelled from its current state")


@bp.post("/orders/<oid>/release_hold")
def release_order_hold(oid):
    authenticate(["DealerAdmin"])
    order = require_fk("orders", oid, "order")
    if order["status"] != "COMPLIANCE_HOLD":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only a COMPLIANCE_HOLD order can be released")
    lines = lines_of_order(order["id"])
    for line in lines:
        variety = db.get("varieties", line["variety_id"])
        if variety is not None:
            check_trait_gate(order["grower_id"], variety)
    allocation = plan_allocation(lines)
    apply_allocation(allocation)
    order["status"] = "CONFIRMED"
    db.touch(order)
    return success_obj(db.public(order), 200)


@bp.post("/orders/<oid>/prepay")
def prepay_order(oid):
    uid, role = authenticate(["SalesRep", "Grower"])
    order = require_fk("orders", oid, "order")
    _order_viewable_grower_check(uid, role, order)
    body = body_json()
    check_shape(body, {"amount_cents": {"type": "integer", "required": True, "min": 1}})
    amount = body["amount_cents"]
    if order["status"] != "CONFIRMED" or order["payment_status"] != "UNPAID":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "order must be CONFIRMED and UNPAID to prepay")
    program = db.get("programs", order["program_id"])
    clock = db.now()
    eligible = [t for t in program.get("prepay_tiers", []) if clock <= dt_of(t, "pay_by")]
    if not eligible:
        raise ApiError(ERR_PREPAY_WINDOW_CLOSED, 409, "no prepay tier window remains open")
    best_bps = max(t["discount_bps"] for t in eligible)
    net_before = order["gross_amount_cents"] - order["rebate_amount_cents"]
    discount = rhu_div(net_before * best_bps, 10000)
    net_due = net_before - discount
    if amount < net_due:
        raise ApiError(ERR_PREPAY_AMOUNT_INSUFFICIENT, 409, "amount_cents below the post-discount net due")
    grower = db.get("growers", order["grower_id"])
    order["prepay_discount_cents"] = discount
    order["net_amount_cents"] = net_due
    order["prepaid_amount_cents"] = amount
    grower["prepay_balance_cents"] += amount
    order["payment_status"] = "PREPAID"
    db.touch(grower)
    db.touch(order)
    return success_obj(db.public(order), 200)


@bp.post("/orders/<oid>/record_payment")
def record_payment(oid):
    authenticate(["DealerAdmin", "SalesRep"])
    order = require_fk("orders", oid, "order")
    body = body_json()
    check_shape(body, {"amount_cents": {"type": "integer", "required": True, "min": 1}})
    amount = body["amount_cents"]
    if order["status"] not in ("CONFIRMED", "CLOSED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "payments record against CONFIRMED or CLOSED orders")
    if order["payment_status"] != "INVOICED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "order is not INVOICED")
    grower = db.get("growers", order["grower_id"])
    order["paid_amount_cents"] += amount
    grower["outstanding_balance_cents"] -= amount
    if order["paid_amount_cents"] >= order["net_amount_cents"]:
        order["payment_status"] = "SETTLED"
    db.touch(grower)
    db.touch(order)
    return success_obj(db.public(order), 200)
