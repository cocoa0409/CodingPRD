"""Order placement, routing, hub selection, fulfilment and cancellation."""
from flask import Blueprint

import calc
import services
import validation as v
from auth import (
    COOK,
    DINER,
    FINANCE_OPERATOR,
    PLATFORM_ADMIN,
    SAFETY_OFFICER,
    acting_role,
    acting_user,
    guard,
)
from core import ApiError, created, db, new_row, ok, parse_dt, public, touch
from listing import list_rows

bp = Blueprint("orders", __name__)

ORDER_READ_ROLES = [COOK, DINER, FINANCE_OPERATOR, SAFETY_OFFICER, PLATFORM_ADMIN]
FULFILMENT_STATUSES = [
    "PLACED",
    "ROUTED",
    "IN_PRODUCTION",
    "HANDED_OFF",
    "DELIVERED",
    "CANCELLED",
]


def find_order(order_id):
    order = db.orders.get(order_id)
    if order is None:
        raise ApiError("ERR_ORDER_NOT_FOUND")
    return order


@bp.route("/orders", methods=["POST"])
@guard([DINER, PLATFORM_ADMIN])
def place_order():
    body = v.body()
    menu_item_id = v.s_id(body, "menu_item_id")
    window_id = v.s_id(body, "production_window_id")
    zone_id = v.s_id(body, "delivery_zone_id")
    quantity = v.s_int(body, "quantity")
    contact_email = v.s_str(body, "diner_contact_email", 1, 320)

    item = db.menu_items.get(menu_item_id)
    if item is None:
        raise ApiError("ERR_MENU_ITEM_NOT_FOUND")
    window = db.windows.get(window_id)
    if window is None:
        raise ApiError("ERR_WINDOW_NOT_FOUND")
    zone = db.zones.get(zone_id)
    if zone is None:
        raise ApiError("ERR_ZONE_NOT_FOUND")

    # cook_id is copied from the menu item; any client-supplied value is ignored.
    cook = db.cooks[item["cook_id"]]

    if cook["onboarding_status"] != "ACTIVE":
        raise ApiError("ERR_COOK_NOT_ACTIVE", "the cook is not ACTIVE")
    if item["review_status"] != "APPROVED":
        raise ApiError("ERR_MENU_ITEM_NOT_APPROVED", "the dish is not APPROVED")
    if window["status"] != "OPEN" or db.now() >= parse_dt(window["order_cutoff_at"]):
        raise ApiError("ERR_WINDOW_CUTOFF_PASSED", "the window no longer accepts orders")
    if cook["compliance_standing"] not in ("CLEAR", "WARNED"):
        raise ApiError("ERR_COOK_SUSPENDED", "the cook may not receive new orders")
    if not calc.has_live_cert(cook["id"]):
        raise ApiError("ERR_CERT_EXPIRED", "the cook holds no unexpired food-handler certificate")
    if quantity < 1 or quantity > 20:
        raise ApiError("ERR_INVALID_QUANTITY", "quantity must be between 1 and 20")
    if zone["state_code"] != cook["state_code"]:
        raise ApiError("ERR_ZONE_STATE_MISMATCH", "the zone is outside the cook's state")

    policy = calc.policy_for_cook(cook)
    pricing = calc.order_pricing(item, quantity, cook)
    projected = (
        int(cook["ytd_cottage_revenue_cents"])
        + calc.in_flight_exposure(cook["id"])
        + pricing["subtotal_cents"]
    )
    if projected > int(policy["cottage_food_annual_cap_cents"]):
        raise ApiError("ERR_COTTAGE_CAP_EXCEEDED", "the projected cottage-food revenue exceeds the cap")
    if not calc.admission_check(window, quantity):
        raise ApiError("ERR_WINDOW_CAPACITY_EXCEEDED", "the window has no effective capacity left")

    row = new_row(
        db.orders,
        {
            "cook_id": cook["id"],
            "menu_item_id": menu_item_id,
            "production_window_id": window_id,
            "delivery_zone_id": zone_id,
            "pickup_hub_id": None,
            "diner_user_id": acting_user(),
            "diner_contact_email": contact_email,
            "quantity": quantity,
            "unit_price_cents_snapshot": pricing["unit_price_cents_snapshot"],
            "subtotal_cents": pricing["subtotal_cents"],
            "cold_chain_surcharge_cents": 0,
            "diner_service_fee_cents": pricing["diner_service_fee_cents"],
            "total_charge_cents": pricing["total_charge_cents"],
            "commission_rate": pricing["commission_rate"],
            "platform_commission_cents": pricing["platform_commission_cents"],
            "cook_earnings_cents": pricing["cook_earnings_cents"],
            "routing_mode": None,
            "fulfillment_status": "PLACED",
            "payment_status": "AUTHORIZED",
            "captured_at": None,
            "effective_year": None,
            "refunded_cents": 0,
            "cook_chargeback_cents": 0,
            "commission_reversed_cents": 0,
            "platform_absorbed_cents": 0,
            "cancelled_reason": None,
        },
    )
    window["committed_meals"] = int(window["committed_meals"]) + quantity
    calc.derive_window_capacity(window)
    touch(window)
    return created(public(row))


@bp.route("/orders/<order_id>", methods=["GET"])
@guard(ORDER_READ_ROLES)
def get_order(order_id):
    return ok(public(find_order(order_id)))


@bp.route("/orders", methods=["GET"])
@guard(ORDER_READ_ROLES)
def list_orders():
    return list_rows(
        list(db.orders.values()),
        [
            "cook_id",
            "menu_item_id",
            "production_window_id",
            "delivery_zone_id",
            "pickup_hub_id",
            "fulfillment_status",
            "payment_status",
        ],
    )


@bp.route("/orders/<order_id>/route", methods=["POST"])
@guard([PLATFORM_ADMIN, FINANCE_OPERATOR])
def route_order(order_id):
    v.body()
    order = find_order(order_id)
    window = db.windows[order["production_window_id"]]
    zone = db.zones[order["delivery_zone_id"]]
    item = db.menu_items[order["menu_item_id"]]
    cook = db.cooks[order["cook_id"]]

    if order["fulfillment_status"] != "PLACED":
        raise ApiError("ERR_INVALID_ORDER_TRANSITION", "routing is legal only from PLACED")
    if window["status"] not in ("OPEN", "CUTOFF_PASSED"):
        raise ApiError(
            "ERR_INVALID_ORDER_TRANSITION", "the owning window must be OPEN or CUTOFF_PASSED"
        )
    if cook["compliance_standing"] in ("SUSPENDED", "REVOKED"):
        raise ApiError("ERR_INVALID_ORDER_TRANSITION", "a suspended or revoked cook cannot route")

    routing_mode = calc.routing_mode_for(item, zone, window, cook)
    calc.cold_chain_check(item, zone, window, routing_mode)

    selected_hub = None
    if zone["service_mode"] == "HUB_PICKUP":
        candidates = calc.eligible_hubs(zone["id"], window)
        if not candidates:
            raise ApiError("ERR_NO_ELIGIBLE_HUB", "no hub survives the eligibility filter")
        selected_hub = calc.rank_hubs(candidates)[0]
        if calc.hub_slot_conflict(selected_hub, window):
            raise ApiError(
                "ERR_HUB_SLOT_CONFLICT", "the selected hub already holds a colliding window"
            )

    surcharge = calc.surcharge_for(item, zone, int(order["quantity"]))
    order["routing_mode"] = routing_mode
    order["cold_chain_surcharge_cents"] = surcharge
    order["total_charge_cents"] = (
        int(order["subtotal_cents"]) + surcharge + int(order["diner_service_fee_cents"])
    )
    order["fulfillment_status"] = "ROUTED"
    if selected_hub is not None:
        order["pickup_hub_id"] = selected_hub["id"]
    touch(order)
    if selected_hub is not None:
        services.recompute_hub(selected_hub)
    return ok(public(order))


@bp.route("/orders/<order_id>/advance", methods=["POST"])
@guard([COOK, DINER, PLATFORM_ADMIN])
def advance_order(order_id):
    body = v.body()
    to_status = v.s_enum(body, "to_status", FULFILMENT_STATUSES)
    order = find_order(order_id)
    window = db.windows[order["production_window_id"]]
    status = order["fulfillment_status"]

    if to_status == "IN_PRODUCTION":
        if status != "ROUTED":
            raise ApiError(
                "ERR_INVALID_ORDER_TRANSITION", "IN_PRODUCTION is reachable from ROUTED"
            )
        if window["status"] != "IN_PRODUCTION":
            raise ApiError(
                "ERR_INVALID_ORDER_TRANSITION", "the owning window is not IN_PRODUCTION"
            )
        order["fulfillment_status"] = "IN_PRODUCTION"
        touch(order)
        return ok(public(order))

    if to_status == "HANDED_OFF":
        if status != "IN_PRODUCTION":
            raise ApiError(
                "ERR_INVALID_ORDER_TRANSITION", "HANDED_OFF is reachable from IN_PRODUCTION"
            )
        if db.now() < parse_dt(window["handoff_start_at"]):
            raise ApiError("ERR_HANDOFF_NOT_STARTED", "the handoff interval has not opened")
        order["fulfillment_status"] = "HANDED_OFF"
        touch(order)
        return ok(public(order))

    if to_status == "DELIVERED":
        if status != "HANDED_OFF":
            raise ApiError(
                "ERR_INVALID_ORDER_TRANSITION", "DELIVERED is reachable from HANDED_OFF"
            )
        order["fulfillment_status"] = "DELIVERED"
        captured = False
        if order["payment_status"] == "AUTHORIZED":
            services.capture_order(order)
            captured = True
        touch(order)
        if captured:
            services.recompute_cook_money(db.cooks[order["cook_id"]])
        return ok(public(order))

    raise ApiError("ERR_INVALID_ORDER_TRANSITION", "%s is not reachable by advancement" % to_status)


@bp.route("/orders/<order_id>/cancel", methods=["POST"])
@guard([DINER, COOK, PLATFORM_ADMIN])
def cancel_order_endpoint(order_id):
    body = v.body()
    v.s_str(body, "reason", 0, 2000, required=False)
    order = find_order(order_id)

    if order["fulfillment_status"] not in ("PLACED", "ROUTED"):
        raise ApiError(
            "ERR_INVALID_ORDER_TRANSITION", "cancellation is legal only from PLACED or ROUTED"
        )
    if acting_role() == DINER and acting_user() != order["diner_user_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "the order belongs to another diner")

    services.cancel_order(order, "DINER_REQUEST")
    return ok(public(order))
