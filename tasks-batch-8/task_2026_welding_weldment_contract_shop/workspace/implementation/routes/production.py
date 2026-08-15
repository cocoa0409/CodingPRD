"""Fixtures, shop orders, weldments (nested routes)."""

from decimal import Decimal
from flask import Blueprint

from db import db
from errors import (
    ApiError, ERR_STALE_VERSION, ERR_WELDMENT_NOT_OPEN, ERR_WELDMENT_HAS_PASSES,
    ERR_JOINTS_NOT_WELDED_OUT, ERR_JOINTS_NOT_NDT_PASSED, ERR_TRAVELER_INCOMPLETE,
    ERR_FIXTURE_NOT_DISPOSITIONED, invalid_request, invalid_state,
)
from helpers import (
    json_body, require_fields, parse_int, parse_datetime, paginate, OWNER_PARTIES,
    STEP_CODES,
)
from middleware import require_roles, require_any
from response import success_object, success_list
from serializers import fixture_out, order_out, weldment_out
from services import (
    stamp_new, make_versioned, mutate, get_shop, get_fixture, get_order,
    get_weldment, joints_of_weldment, cancel_weldment_cascade,
    cascade_fixture_on_terminal, cascade_order_on_ship, reports_of_weldment,
)

bp = Blueprint("production", __name__)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@bp.route("/weld-shop/shops/<shop_id>/fixtures", methods=["POST"])
@require_roles("ProductionPlanner")
def create_fixture(user_id, role, shop_id):
    shop = get_shop(shop_id)
    body = json_body()
    require_fields(body, ["fixture_code", "capacity_weldments", "owner_party"])
    if not isinstance(body["fixture_code"], str):
        raise invalid_request("fixture_code must be a string")
    capacity = parse_int(body["capacity_weldments"], "capacity_weldments")
    if capacity < 1:
        raise invalid_request("capacity_weldments must be >= 1")
    if body["owner_party"] not in OWNER_PARTIES:
        raise invalid_request("owner_party must be SHOP or CUSTOMER")
    fixture = stamp_new({
        "shop_id": shop["id"],
        "fixture_code": body["fixture_code"],
        "capacity_weldments": capacity,
        "owner_party": body["owner_party"],
        "status": "AVAILABLE",
    })
    make_versioned(fixture)
    db.fixtures[fixture["id"]] = fixture
    return success_object(fixture_out(fixture), status=201)


@bp.route("/weld-shop/shops/<shop_id>/fixtures", methods=["GET"])
@require_any
def list_fixtures(user_id, role, shop_id):
    shop = get_shop(shop_id)
    records = [f for f in db.fixtures.values() if f["shop_id"] == shop["id"]]
    page, limit, offset, total = paginate(records)
    return success_list([fixture_out(f) for f in page], limit, offset, total)


@bp.route("/weld-shop/shops/<shop_id>/fixtures/<fixture_id>/reserve", methods=["POST"])
@require_roles("ProductionPlanner")
def reserve_fixture(user_id, role, shop_id, fixture_id):
    get_shop(shop_id)
    fixture = get_fixture(shop_id, fixture_id)
    if fixture["status"] != "AVAILABLE":
        raise invalid_state("Fixture must be AVAILABLE to reserve")
    fixture["status"] = "RESERVED"
    mutate(fixture)
    return success_object(fixture_out(fixture))


@bp.route("/weld-shop/shops/<shop_id>/fixtures/<fixture_id>/release", methods=["POST"])
@require_roles("ProductionPlanner")
def release_fixture(user_id, role, shop_id, fixture_id):
    get_shop(shop_id)
    fixture = get_fixture(shop_id, fixture_id)
    if fixture["status"] != "RESERVED":
        raise invalid_state("Fixture must be RESERVED to release")
    in_use_by = any(
        w["fixture_id"] == fixture["id"] and w["posture"] not in ("SHIPPED", "CANCELLED")
        for w in db.weldments.values()
    )
    if in_use_by:
        raise invalid_state(
            "Fixture is referenced by a non-terminal weldment and cannot be released")
    fixture["status"] = "AVAILABLE"
    mutate(fixture)
    return success_object(fixture_out(fixture))


@bp.route("/weld-shop/shops/<shop_id>/fixtures/<fixture_id>/send-for-repair", methods=["POST"])
@require_roles("ProductionPlanner")
def send_fixture_for_repair(user_id, role, shop_id, fixture_id):
    get_shop(shop_id)
    fixture = get_fixture(shop_id, fixture_id)
    if fixture["status"] != "IN_USE":
        raise invalid_state("Fixture must be IN_USE to send for repair")
    active = any(
        w["fixture_id"] == fixture["id"] and w["posture"] not in ("SHIPPED", "CANCELLED")
        for w in db.weldments.values()
    )
    if active:
        raise invalid_state(
            "All weldments referencing the fixture must be SHIPPED or CANCELLED")
    fixture["status"] = "UNDER_REPAIR"
    mutate(fixture)
    return success_object(fixture_out(fixture))


# ---------------------------------------------------------------------------
# Shop orders
# ---------------------------------------------------------------------------

@bp.route("/weld-shop/shops/<shop_id>/shop-orders", methods=["POST"])
@require_roles("ProductionPlanner")
def create_order(user_id, role, shop_id):
    shop = get_shop(shop_id)
    body = json_body()
    require_fields(body, ["po_number", "customer_name", "promised_ship_date_utc"])
    if not isinstance(body["po_number"], str) or not isinstance(body["customer_name"], str):
        raise invalid_request("po_number and customer_name must be strings")
    promised = parse_datetime(body["promised_ship_date_utc"], "promised_ship_date_utc")
    order = stamp_new({
        "shop_id": shop["id"],
        "po_number": body["po_number"],
        "customer_name": body["customer_name"],
        "promised_ship_date_utc": promised,
        "status": "OPEN",
    })
    make_versioned(order)
    db.orders[order["id"]] = order
    return success_object(order_out(order), status=201)


@bp.route("/weld-shop/shops/<shop_id>/shop-orders", methods=["GET"])
@require_any
def list_orders(user_id, role, shop_id):
    shop = get_shop(shop_id)
    records = [o for o in db.orders.values() if o["shop_id"] == shop["id"]]
    page, limit, offset, total = paginate(records)
    return success_list([order_out(o) for o in page], limit, offset, total)


@bp.route("/weld-shop/shops/<shop_id>/shop-orders/<order_id>", methods=["GET"])
@require_any
def get_order_route(user_id, role, shop_id, order_id):
    get_shop(shop_id)
    return success_object(order_out(get_order(shop_id, order_id)))


# ---------------------------------------------------------------------------
# Weldments
# ---------------------------------------------------------------------------

@bp.route("/weld-shop/shops/<shop_id>/shop-orders/<order_id>/weldments", methods=["POST"])
@require_roles("ProductionPlanner")
def create_weldment(user_id, role, shop_id, order_id):
    shop = get_shop(shop_id)
    order = get_order(shop_id, order_id)
    body = json_body()
    require_fields(body, ["weldment_serial", "fixture_id", "drawing_revision"])
    if not isinstance(body["weldment_serial"], str):
        raise invalid_request("weldment_serial must be a string")
    fixture = get_fixture(shop_id, body["fixture_id"])
    wm = stamp_new({
        "shop_id": shop["id"],
        "shop_order_id": order["id"],
        "weldment_serial": body["weldment_serial"],
        "fixture_id": fixture["id"],
        "drawing_revision": body["drawing_revision"],
        "posture": "OPEN",
        "repair_pass_count": 0,
        "total_pass_count": 0,
        "repair_rate_pct": Decimal("0"),
        "distortion_count": 0,
        "signed_off_at_utc": None,
    })
    make_versioned(wm)
    db.weldments[wm["id"]] = wm
    if order["status"] == "OPEN":
        order["status"] = "IN_PROGRESS"
        mutate(order)
    return success_object(weldment_out(wm), status=201)


@bp.route("/weld-shop/shops/<shop_id>/shop-orders/<order_id>/weldments", methods=["GET"])
@require_any
def list_weldments_under_order(user_id, role, shop_id, order_id):
    shop = get_shop(shop_id)
    order = get_order(shop_id, order_id)
    records = [w for w in db.weldments.values() if w["shop_order_id"] == order["id"]]
    page, limit, offset, total = paginate(records)
    return success_list([weldment_out(w) for w in page], limit, offset, total)


@bp.route("/weld-shop/shops/<shop_id>/weldments/<weldment_id>", methods=["GET"])
@require_any
def get_weldment_route(user_id, role, shop_id, weldment_id):
    get_shop(shop_id)
    return success_object(weldment_out(get_weldment(shop_id, weldment_id)))


@bp.route("/weld-shop/shops/<shop_id>/weldments/<weldment_id>/ship", methods=["POST"])
@require_roles("ShippingClerk")
def ship_weldment(user_id, role, shop_id, weldment_id):
    shop = get_shop(shop_id)
    wm = get_weldment(shop_id, weldment_id)
    # OCC gate (expected_weldment_version non-optional)
    body = json_body()
    if "expected_weldment_version" not in body or body["expected_weldment_version"] is None:
        raise invalid_request("Missing required field: expected_weldment_version")
    expected = parse_int(body["expected_weldment_version"], "expected_weldment_version")
    if expected != wm["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_weldment_version does not match current version")
    if wm["posture"] != "OPEN":
        raise ApiError(ERR_WELDMENT_NOT_OPEN, 409,
                       "Weldment posture not OPEN; ship blocked")
    joints = joints_of_weldment(wm["id"])
    if any(j["fabrication_status"] != "WELDED_OUT" for j in joints):
        raise ApiError(ERR_JOINTS_NOT_WELDED_OUT, 409,
                       "Ship requires all joints fabrication_status == WELDED_OUT")
    if any(j["inspection_status"] != "NDT_PASSED" for j in joints):
        raise ApiError(ERR_JOINTS_NOT_NDT_PASSED, 409,
                       "Ship requires all joints inspection_status == NDT_PASSED")
    signed_steps = {
        s["step_code"] for s in db.sign_offs.values() if s["weldment_id"] == wm["id"]
    }
    if not set(STEP_CODES) <= signed_steps:
        raise ApiError(ERR_TRAVELER_INCOMPLETE, 409,
                       "One or more required traveler steps missing")
    fixture = db.fixtures.get(wm["fixture_id"])
    if fixture is None:
        raise ApiError(ERR_FIXTURE_NOT_DISPOSITIONED, 409,
                       "Fixture ownership disposition incomplete at ship")
    if fixture["owner_party"] == "CUSTOMER":
        # no release-to-customer record type exists in the API surface
        raise ApiError(ERR_FIXTURE_NOT_DISPOSITIONED, 409,
                       "Fixture ownership disposition incomplete at ship")
    if fixture["status"] not in ("AVAILABLE", "IN_USE"):
        raise ApiError(ERR_FIXTURE_NOT_DISPOSITIONED, 409,
                       "Fixture ownership disposition incomplete at ship")
    wm["posture"] = "SHIPPED"
    wm["signed_off_at_utc"] = shop["current_utc"]
    mutate(wm)
    cascade_fixture_on_terminal(wm)
    cascade_order_on_ship(wm)
    return success_object(weldment_out(wm))


@bp.route("/weld-shop/shops/<shop_id>/weldments/<weldment_id>/cancel", methods=["POST"])
@require_roles("ProductionPlanner")
def cancel_weldment(user_id, role, shop_id, weldment_id):
    get_shop(shop_id)
    wm = get_weldment(shop_id, weldment_id)
    if wm["posture"] != "OPEN":
        raise invalid_state("Weldment must be OPEN to cancel")
    joint_ids = {j["id"] for j in joints_of_weldment(wm["id"])}
    has_passes = any(p["joint_id"] in joint_ids for p in db.weld_passes.values())
    if has_passes:
        raise ApiError(ERR_WELDMENT_HAS_PASSES, 409,
                       "Cannot cancel weldment with recorded weld passes")
    cancel_weldment_cascade(wm)
    return success_object(weldment_out(wm))


@bp.route("/weld-shop/shops/<shop_id>/weldments/<weldment_id>/clear-repair-review", methods=["POST"])
@require_roles("QCManager")
def clear_repair_review(user_id, role, shop_id, weldment_id):
    get_shop(shop_id)
    wm = get_weldment(shop_id, weldment_id)
    if wm["posture"] != "REPAIR_REVIEW":
        raise invalid_state("Weldment is not in REPAIR_REVIEW posture")
    if any(r["disposition"] == "PENDING" for r in reports_of_weldment(wm["id"])):
        raise invalid_state("Distortion reports still PENDING on this weldment")
    wm["posture"] = "OPEN"
    mutate(wm)
    return success_object(weldment_out(wm))


@bp.route("/weld-shop/shops/<shop_id>/weldments/<weldment_id>/unfreeze", methods=["POST"])
@require_roles("QCManager")
def unfreeze_weldment(user_id, role, shop_id, weldment_id):
    get_shop(shop_id)
    wm = get_weldment(shop_id, weldment_id)
    if wm["posture"] != "FROZEN":
        raise invalid_state("Weldment is not FROZEN")
    unresolved = any(
        j["inspection_status"] == "NDT_FAILED" for j in joints_of_weldment(wm["id"])
    )
    if unresolved:
        raise invalid_state(
            "All NDT_FAILED joints must move to REPAIR_REQUIRED or REPAIR_WELDED_OUT")
    wm["posture"] = "OPEN"
    mutate(wm)
    return success_object(weldment_out(wm))
