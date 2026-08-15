"""MealOrder pipeline (PRD 3.5, 3.7)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_VALIDATION, ERR_INVALID_STATE, ERR_REFERENCE_INVALID,
    ERR_CONSTRAINT_VIOLATION, ERR_CAPACITY_FULL, ERR_DELIVERY_OUT_OF_RANGE,
    ERR_ALLERGEN_CONFLICT, ERR_GUEST_FLAGGED_NEEDS_REVIEW, ERR_UNAUTHORIZED_ROLE,
)
from helpers import (
    get_body, req_field, req_int, opt_field, stamp_new, get_or_404, touch,
)
from middleware import get_caller, check_role_allowed
from response import success_object
from routes.common import public
from services import core
from util import CLOCK

bp = Blueprint("meal_orders", __name__)

VOL = ["Volunteer"]


@bp.route("/kitchen/meal-orders", methods=["POST"])
def create_order():
    body = get_body()
    caller = get_caller()
    check_role_allowed(caller, ["Guest", "KitchenManager"])

    meal_service_id = req_field(body, "meal_service_id", str)
    guest_id = req_field(body, "guest_id", str)
    menu_item_id = req_field(body, "menu_item_id", str)
    quantity = req_int(body, "quantity", minimum=1)
    substitution_allowed = opt_field(body, "substitution_allowed", bool, True)

    svc = db["meal_services"].get(meal_service_id)
    if svc is None:
        raise_error(ERR_REFERENCE_INVALID, f"meal service not found: {meal_service_id}")
    guest = db["guests"].get(guest_id)
    if guest is None:
        raise_error(ERR_REFERENCE_INVALID, f"guest not found: {guest_id}")
    item = db["menu_items"].get(menu_item_id)

    # State: service must be OPEN
    if svc["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, f"service is {svc['status']}, not OPEN")

    # Referential integrity with state
    if guest["status"] == "INACTIVE":
        raise_error(ERR_REFERENCE_INVALID, "guest is INACTIVE")
    if guest["status"] == "FLAGGED" and caller.role == "Guest":
        raise_error(ERR_GUEST_FLAGGED_NEEDS_REVIEW,
                    "FLAGGED guest orders require KitchenManager approval")
    if caller.role == "Guest" and guest_id != caller.user_id:
        raise_error(ERR_UNAUTHORIZED_ROLE,
                    "a guest may only create orders for themselves")

    if item is None or item["menu_day_id"] != svc["menu_day_id"]:
        raise_error(ERR_REFERENCE_INVALID,
                    "menu item does not belong to the service's menu day")
    if item["status"] != "CONFIRMED":
        raise_error(ERR_REFERENCE_INVALID, f"menu item is {item['status']}, not CONFIRMED")

    # Allergen gate at creation
    if core.item_allergens(item) & set(guest.get("allergens") or []):
        raise_error(ERR_ALLERGEN_CONFLICT,
                    "item allergen_tags intersect the guest's allergens")

    # Shape: quantity within household size
    if quantity > guest["household_size"]:
        raise_error(ERR_CONSTRAINT_VIOLATION,
                    "quantity exceeds guest household_size")

    # Delivery radius
    if svc["service_model"] == "DELIVERY":
        site = db["sites"].get(svc["site_id"])
        dist = guest.get("delivery_distance_km")
        if site is not None and dist is not None and dist > site["delivery_radius_km"]:
            raise_error(ERR_DELIVERY_OUT_OF_RANGE,
                        "delivery_distance_km exceeds site delivery_radius_km")

    # Capacity (last gate per PRD 2.6)
    if not (svc["reserved_count"] < svc["capacity"]):
        raise_error(ERR_CAPACITY_FULL, "service reserved_count is at capacity")

    rec = stamp_new({
        "meal_service_id": meal_service_id,
        "guest_id": guest_id,
        "menu_item_id": menu_item_id,
        "quantity": quantity,
        "substitution_allowed": substitution_allowed,
        "prep_status": "QUEUED",
        "fulfillment_status": "RESERVED",
        "charge_cents": 0,
    })
    db["meal_orders"][rec["id"]] = rec

    svc["reserved_count"] += 1
    touch(svc)
    core.item_sold_out_reeval(item)
    return success_object(public(rec), 201)


@bp.route("/kitchen/meal-orders/<oid>", methods=["GET"])
def get_order(oid):
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager", "Volunteer", "Guest"])
    rec = get_or_404("meal_orders", oid)
    return success_object(public(rec))


def _require_checked_in_shift(caller, site_id, roles):
    """Caller must be CHECKED_IN on a shift at this site covering now with one of roles."""
    now = CLOCK.now()
    for s in db["volunteer_shifts"].values():
        if (s["volunteer_id"] == caller.user_id
                and s["site_id"] == site_id
                and s["status"] == "CHECKED_IN"
                and s["role_on_shift"] in roles
                and s["_starts_at"] <= now < s["_ends_at"]):
            return s
    return None


@bp.route("/kitchen/meal-orders/<oid>/start-prep", methods=["POST"])
def start_prep(oid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, VOL)
    order = get_or_404("meal_orders", oid)

    svc = db["meal_services"].get(order["meal_service_id"])
    if svc is None or svc["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "service must be OPEN to start prep")
    if order["prep_status"] != "QUEUED":
        raise_error(ERR_INVALID_STATE,
                    f"cannot start prep from {order['prep_status']}")

    if _require_checked_in_shift(caller, svc["site_id"], {"PREP", "COOK"}) is None:
        raise_error(ERR_UNAUTHORIZED_ROLE,
                    "caller must be CHECKED_IN on a PREP or COOK shift at this site covering now")

    order["prep_status"] = "IN_PREP"
    touch(order)
    return success_object(public(order))


@bp.route("/kitchen/meal-orders/<oid>/mark-ready", methods=["POST"])
def mark_ready(oid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, VOL)
    order = get_or_404("meal_orders", oid)

    if order["prep_status"] != "IN_PREP":
        raise_error(ERR_INVALID_STATE,
                    f"cannot mark ready from {order['prep_status']}")

    # Allergen re-check at READY time (item tags incl. batch-propagated)
    item = db["menu_items"].get(order["menu_item_id"])
    guest = db["guests"].get(order["guest_id"])
    if item is not None and guest is not None:
        if core.item_allergens(item) & set(guest.get("allergens") or []):
            raise_error(ERR_ALLERGEN_CONFLICT,
                        "allergen re-check failed at READY time")

    order["prep_status"] = "READY"
    touch(order)
    return success_object(public(order))


@bp.route("/kitchen/meal-orders/<oid>/rework", methods=["POST"])
def rework(oid):
    body = get_body()
    caller = get_caller()
    check_role_allowed(caller, VOL)
    order = get_or_404("meal_orders", oid)

    reason = req_field(body, "reason", str)

    if order["prep_status"] != "READY":
        raise_error(ERR_INVALID_STATE,
                    f"cannot rework from {order['prep_status']}")

    order["prep_status"] = "IN_PREP"
    notes = order.setdefault("audit_notes", [])
    notes.append({"reason": reason, "at": CLOCK.now_iso()})
    touch(order)
    return success_object(public(order))


@bp.route("/kitchen/meal-orders/<oid>/serve", methods=["POST"])
def serve(oid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, VOL)
    order = get_or_404("meal_orders", oid)

    svc = db["meal_services"].get(order["meal_service_id"])
    if svc is None or svc["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "service must be OPEN to serve")
    if order["fulfillment_status"] != "RESERVED":
        raise_error(ERR_INVALID_STATE,
                    f"cannot serve from {order['fulfillment_status']}")
    if order["prep_status"] != "READY":
        raise_error(ERR_INVALID_STATE, "order prep_status must be READY to serve")
    if svc["service_model"] != "DINE_IN":
        raise_error(ERR_INVALID_STATE, "serve is only valid for DINE_IN services")

    core.fulfill_order(order, "SERVED")
    return success_object(public(order))


@bp.route("/kitchen/meal-orders/<oid>/deliver", methods=["POST"])
def deliver(oid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, VOL)
    order = get_or_404("meal_orders", oid)

    svc = db["meal_services"].get(order["meal_service_id"])
    if svc is None or svc["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "service must be OPEN to deliver")
    if order["fulfillment_status"] != "RESERVED":
        raise_error(ERR_INVALID_STATE,
                    f"cannot deliver from {order['fulfillment_status']}")
    if order["prep_status"] != "READY":
        raise_error(ERR_INVALID_STATE, "order prep_status must be READY to deliver")
    if svc["service_model"] != "DELIVERY":
        raise_error(ERR_INVALID_STATE, "deliver is only valid for DELIVERY services")

    if _require_checked_in_shift(caller, svc["site_id"], {"DRIVER"}) is None:
        raise_error(ERR_UNAUTHORIZED_ROLE,
                    "caller must be CHECKED_IN on a DRIVER shift at this site covering now")

    core.fulfill_order(order, "DELIVERED")
    return success_object(public(order))


@bp.route("/kitchen/meal-orders/<oid>/release", methods=["POST"])
def release(oid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, ["Guest", "KitchenManager"])
    order = get_or_404("meal_orders", oid)

    if order["fulfillment_status"] != "RESERVED":
        raise_error(ERR_INVALID_STATE,
                    f"cannot release from {order['fulfillment_status']}")

    if caller.role == "Guest":
        if order["guest_id"] != caller.user_id:
            raise_error(ERR_UNAUTHORIZED_ROLE,
                        "a guest may only release their own order")
        svc = db["meal_services"].get(order["meal_service_id"])
        if svc is not None and not (CLOCK.now() < svc["_window_start"]):
            raise_error(ERR_INVALID_STATE,
                        "a guest may only release before the service window_start")

    core.release_order(order, actor=caller.role)
    return success_object(public(order))
