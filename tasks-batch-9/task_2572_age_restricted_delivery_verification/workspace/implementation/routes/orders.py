"""Orders, order lines, submission, the compliance read model, clearance,
dispatch and return settlement."""
from decimal import Decimal

from flask import Blueprint, g

from db import (
    DISPATCHABLE_COMPLIANCE_STATES,
    RESTRICTION_CLASSES,
    db,
    new_row,
    now,
    now_str,
    sort_key,
    touch,
)
from errors import ApiError
from middleware import (
    COMPLIANCE_OFFICER,
    COURIER,
    CUSTOMER,
    PARTNER_MANAGER,
    PLATFORM_ADMIN,
    auth,
    fetch,
    scope_check,
    scope_if,
)
from response import created, listing, ok, pagination, public
from services.battery import evaluate_order
from services.calc import ZERO2, compute_restriction_types, order_lines_of
from services.parties import refresh_partner, settlement_figures
from util import dec, fmt_dt, parse_dt, rhu
import validate as v

bp = Blueprint("orders", __name__)

COMPLIANCE_STATES = (
    "DRAFT_UNVERIFIED",
    "AUTO_CLEARED",
    "PREVERIFIED",
    "PENDING_COMPLIANCE_REVIEW",
    "COMPLIANCE_CLEARED",
    "COMPLIANCE_BLOCKED",
)
FULFILLMENT_STATES = (
    "CREATED",
    "SUBMITTED",
    "DISPATCHED",
    "HELD_AT_HUB",
    "OUT_FOR_DELIVERY",
    "DELIVERED",
    "RETURN_IN_TRANSIT",
    "RETURN_COMPLETED",
)
LINE_STATES = ("INCLUDED", "WITHDRAWN")


def _recompute_order_totals(order):
    lines = order_lines_of(order)
    order["item_subtotal_cents"] = sum(l["line_total_cents"] for l in lines)
    order["restriction_types"] = compute_restriction_types(order)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------
@bp.post("/orders")
def create_order():
    auth(CUSTOMER)
    body = v.body()
    customer_id = body.get("customer_id")
    if isinstance(customer_id, str) and customer_id.strip() != "":
        scope_check(customer_id)
    else:
        raise ApiError("ERR_VALIDATION", "customer_id is required")
    fetch("customers", customer_id)
    jurisdiction_id = body.get("delivery_jurisdiction_id")
    if not isinstance(jurisdiction_id, str) or jurisdiction_id.strip() == "":
        raise ApiError("ERR_VALIDATION", "delivery_jurisdiction_id is required")
    fetch("jurisdictions", jurisdiction_id)
    partner_id = body.get("delivery_partner_id")
    if not isinstance(partner_id, str) or partner_id.strip() == "":
        raise ApiError("ERR_VALIDATION", "delivery_partner_id is required")
    fetch("partners", partner_id)
    _scheduled, scheduled_raw = v.req_dt(body, "scheduled_delivery_at")
    delivery_fee_cents = v.req_int(body, "delivery_fee_cents", 0)

    row = new_row(
        customer_id=customer_id,
        delivery_jurisdiction_id=jurisdiction_id,
        delivery_partner_id=partner_id,
        scheduled_delivery_at=scheduled_raw,
        delivery_fee_cents=delivery_fee_cents,
        item_subtotal_cents=0,
        charged_cents=0,
        provisional_restricted_units=ZERO2,
        final_restricted_units=None,
        restocking_fee_cents=0,
        refunded_cents=0,
        retained_cents=0,
        compliance_state="DRAFT_UNVERIFIED",
        fulfillment_state="CREATED",
        restriction_types=[],
        applied_policy_ids=[],
        submitted_at=None,
        dispatched_at=None,
        delivered_at=None,
        hold_reason=None,
        clearance_actor_user_id=None,
    )
    db.orders[row["id"]] = row
    return created(public(row))


@bp.get("/orders/<order_id>")
def get_order(order_id):
    auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER, PARTNER_MANAGER, CUSTOMER, COURIER)
    order = fetch("orders", order_id)
    scope_if(CUSTOMER, order["customer_id"])
    scope_if(PARTNER_MANAGER, order["delivery_partner_id"])
    return ok(public(order))


@bp.get("/orders")
def list_orders():
    user_id, role = auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER, PARTNER_MANAGER, CUSTOMER)
    customer_filter = v.str_filter("customer_id")
    partner_filter = v.str_filter("delivery_partner_id")
    jurisdiction_filter = v.str_filter("delivery_jurisdiction_id")
    compliance_state = v.enum_filter("compliance_state", COMPLIANCE_STATES)
    fulfillment_state = v.enum_filter("fulfillment_state", FULFILLMENT_STATES)
    limit, offset = pagination()
    if role == CUSTOMER:
        if customer_filter is not None and customer_filter != user_id:
            raise ApiError("ERR_FORBIDDEN_RESOURCE_SCOPE")
        customer_filter = user_id
    if role == PARTNER_MANAGER:
        if partner_filter is not None and partner_filter != user_id:
            raise ApiError("ERR_FORBIDDEN_RESOURCE_SCOPE")
        partner_filter = user_id
    rows = list(db.orders.values())
    if customer_filter is not None:
        rows = [r for r in rows if r["customer_id"] == customer_filter]
    if partner_filter is not None:
        rows = [r for r in rows if r["delivery_partner_id"] == partner_filter]
    if jurisdiction_filter is not None:
        rows = [r for r in rows if r["delivery_jurisdiction_id"] == jurisdiction_filter]
    if compliance_state is not None:
        rows = [r for r in rows if r["compliance_state"] == compliance_state]
    if fulfillment_state is not None:
        rows = [r for r in rows if r["fulfillment_state"] == fulfillment_state]
    rows.sort(key=sort_key)
    return listing(rows, limit, offset)


# ---------------------------------------------------------------------------
# Order lines
# ---------------------------------------------------------------------------
@bp.post("/orders/<order_id>/lines")
def add_line(order_id):
    auth(CUSTOMER)
    order = fetch("orders", order_id)
    scope_check(order["customer_id"])
    body = v.body()
    product_id = body.get("product_id")
    if not isinstance(product_id, str) or product_id.strip() == "":
        raise ApiError("ERR_VALIDATION", "product_id is required")
    product = fetch("products", product_id)
    quantity = v.req_int(body, "quantity", 1, 500)
    if order["fulfillment_state"] != "CREATED":
        raise ApiError("ERR_INVALID_ORDER_STATE", "lines may only be added while the order is CREATED")

    row = new_row(
        order_id=order_id,
        product_id=product_id,
        quantity=quantity,
        unit_price_cents=product["list_price_cents"],
        units_per_item_snapshot=product["restricted_units_per_item"],
        line_total_cents=quantity * product["list_price_cents"],
        line_restricted_units=ZERO2,
        line_state="INCLUDED",
    )
    db.order_lines[row["id"]] = row
    _recompute_order_totals(order)
    touch(order)
    return created(public(row))


@bp.get("/order-lines/<line_id>")
def get_line(line_id):
    auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER, PARTNER_MANAGER, CUSTOMER)
    line = fetch("order_lines", line_id)
    order = db.orders.get(line["order_id"])
    if order is not None:
        scope_if(CUSTOMER, order["customer_id"])
        scope_if(PARTNER_MANAGER, order["delivery_partner_id"])
    return ok(public(line))


@bp.get("/order-lines")
def list_lines():
    user_id, role = auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER, PARTNER_MANAGER, CUSTOMER)
    order_filter = v.str_filter("order_id")
    product_filter = v.str_filter("product_id")
    line_state = v.enum_filter("line_state", LINE_STATES)
    limit, offset = pagination()
    if order_filter is not None:
        target = db.orders.get(order_filter)
        if target is not None:
            scope_if(CUSTOMER, target["customer_id"])
            scope_if(PARTNER_MANAGER, target["delivery_partner_id"])
    rows = list(db.order_lines.values())
    if role in (CUSTOMER, PARTNER_MANAGER):
        owned = set()
        for order in db.orders.values():
            if role == CUSTOMER and order["customer_id"] == user_id:
                owned.add(order["id"])
            if role == PARTNER_MANAGER and order["delivery_partner_id"] == user_id:
                owned.add(order["id"])
        rows = [r for r in rows if r["order_id"] in owned]
    if order_filter is not None:
        rows = [r for r in rows if r["order_id"] == order_filter]
    if product_filter is not None:
        rows = [r for r in rows if r["product_id"] == product_filter]
    if line_state is not None:
        rows = [r for r in rows if r["line_state"] == line_state]
    rows.sort(key=sort_key)
    return listing(rows, limit, offset)


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------
@bp.post("/orders/<order_id>/submit")
def submit_order(order_id):
    auth(CUSTOMER)
    order = fetch("orders", order_id)
    scope_check(order["customer_id"])
    if order["fulfillment_state"] != "CREATED":
        raise ApiError("ERR_INVALID_ORDER_STATE")
    lines = order_lines_of(order)
    if not lines:
        raise ApiError("ERR_ORDER_HAS_NO_LINES")

    facts = evaluate_order(order)
    if facts["error"] is not None:
        raise ApiError(facts["error"])

    order["item_subtotal_cents"] = sum(l["line_total_cents"] for l in lines)
    order["charged_cents"] = order["item_subtotal_cents"] + order["delivery_fee_cents"]
    order["fulfillment_state"] = "SUBMITTED"
    order["submitted_at"] = now_str()

    if not facts["restriction_types"]:
        order["restriction_types"] = []
        order["applied_policy_ids"] = []
        order["provisional_restricted_units"] = ZERO2
        order["compliance_state"] = "AUTO_CLEARED"
    else:
        order["restriction_types"] = list(facts["restriction_types"])
        order["applied_policy_ids"] = list(facts["applied_policy_ids"])
        order["provisional_restricted_units"] = facts["provisional_total"]
        order["compliance_state"] = facts["route"]
        for line_id, value in facts["line_units"].items():
            line = db.order_lines.get(line_id)
            if line is not None and line["line_restricted_units"] != value:
                line["line_restricted_units"] = value
                touch(line)
    touch(order)
    return ok(public(order))


@bp.get("/orders/<order_id>/compliance-evaluation")
def compliance_evaluation(order_id):
    auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER, CUSTOMER)
    order = fetch("orders", order_id)
    scope_if(CUSTOMER, order["customer_id"])
    facts = evaluate_order(order)
    per_type = []
    for entry in facts["per_type"]:
        policy = entry["policy"]
        exposure = entry["exposure"]
        consumed = entry.get("window_units_consumed", ZERO2)
        per_type.append({
            "restriction_type": entry["restriction_type"],
            "policy_id": policy["id"],
            "exposure": exposure,
            "units": exposure,
            "restricted_units": exposure,
            "provisional_restricted_units": exposure,
            "max_units_per_order": policy["max_units_per_order"],
            "window_units_consumed": consumed,
            "max_units_per_window": policy["max_units_per_window"],
        })
    return ok({
        "order_id": order["id"],
        "restriction_types": facts["restriction_types"],
        "applied_policy_ids": facts["applied_policy_ids"],
        "provisional_restricted_units": facts["provisional_total"],
        "per_type_exposure": per_type,
        "window_units_consumed": facts["window_total"],
        "local_delivery_minute": facts["local_minute"],
        "in_delivery_window": facts["in_window"],
        "purchaser_age_years": facts["purchaser_age_years"],
        "min_age_required": facts["min_age_required"],
        "identity_result": facts["identity_result"],
        "would_route_to": facts["route"],
        "first_blocking_error_id": facts["error"],
    })


# ---------------------------------------------------------------------------
# Clearance, dispatch, settlement
# ---------------------------------------------------------------------------
@bp.post("/orders/<order_id>/clearance")
def clear_order(order_id):
    user_id, _role = auth(COMPLIANCE_OFFICER)
    order = fetch("orders", order_id)
    body = v.body()
    decision = v.req_enum(body, "decision", ("CLEAR", "BLOCK"))
    if order["compliance_state"] != "PENDING_COMPLIANCE_REVIEW":
        raise ApiError("ERR_INVALID_ORDER_STATE")
    partner = db.partners.get(order["delivery_partner_id"])
    if decision == "CLEAR":
        if partner is not None and partner["posture"] == "SUSPENDED":
            raise ApiError("ERR_PARTNER_SUSPENDED")
        order["compliance_state"] = "COMPLIANCE_CLEARED"
        order["clearance_actor_user_id"] = user_id
        order["hold_reason"] = None
    else:
        order["compliance_state"] = "COMPLIANCE_BLOCKED"
        order["clearance_actor_user_id"] = user_id
        if order["fulfillment_state"] in ("DISPATCHED", "HELD_AT_HUB"):
            order["fulfillment_state"] = "SUBMITTED"
            order["dispatched_at"] = None
    touch(order)
    return ok(public(order))


@bp.post("/orders/<order_id>/dispatch")
def dispatch_order(order_id):
    auth(PARTNER_MANAGER)
    order = fetch("orders", order_id)
    scope_check(order["delivery_partner_id"])
    if order["fulfillment_state"] not in ("SUBMITTED", "HELD_AT_HUB"):
        raise ApiError("ERR_INVALID_ORDER_STATE")
    if order["compliance_state"] not in DISPATCHABLE_COMPLIANCE_STATES:
        raise ApiError("ERR_INVALID_ORDER_STATE")
    partner = db.partners.get(order["delivery_partner_id"])
    if partner is not None and partner["posture"] == "SUSPENDED":
        raise ApiError("ERR_PARTNER_SUSPENDED")
    order["fulfillment_state"] = "DISPATCHED"
    order["dispatched_at"] = now_str()
    order["hold_reason"] = None
    touch(order)
    return ok(public(order))


@bp.post("/orders/<order_id>/return-settlement")
def settle_return(order_id):
    auth(PLATFORM_ADMIN)
    order = fetch("orders", order_id)
    body = v.body()
    restock_confirmed = v.req_bool(body, "restock_confirmed")
    if order["fulfillment_state"] != "RETURN_IN_TRANSIT":
        raise ApiError("ERR_INVALID_ORDER_STATE")
    if not restock_confirmed:
        raise ApiError("ERR_RESTOCK_NOT_CONFIRMED")

    figures = settlement_figures(order)
    order["restocking_fee_cents"] = figures["restocking_fee_cents"]
    order["refunded_cents"] = figures["refunded_cents"]
    order["retained_cents"] = figures["retained_cents"]
    for line in order_lines_of(order):
        if line["line_state"] == "INCLUDED":
            line["line_state"] = "WITHDRAWN"
            touch(line)
    order["final_restricted_units"] = ZERO2
    order["fulfillment_state"] = "RETURN_COMPLETED"
    touch(order)
    return ok(public(order))
