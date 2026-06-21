"""Entitlement plans and Lightning Lane purchases (PRD §3.6)."""
from flask import Blueprint, request

import db
import domain
import errors
import lookups
import response
import serialize
import validate_input as vi
from middleware import get_principal, require_roles

bp = Blueprint("plans", __name__)


# ---------------------------------------------------------------------------
# EntitlementPlan create / list
# ---------------------------------------------------------------------------
@bp.post("/parks/<pid>/entitlement-plans")
def create_plan(pid):
    _, role = get_principal()
    require_roles(role, {"ParkAdmin"})
    park = lookups.get_park(pid)
    body = vi.get_body()

    tier = vi.require_enum(body, "tier", {"MULTI_PASS", "SINGLE_PASS"})
    price_cents = vi.require_int(body, "price_cents", min_val=0)
    max_holds = vi.require_int(body, "max_concurrent_holds", min_val=1)
    surge = vi.opt_number(body, "surge_multiplier", default=1.0)
    if surge < 1.0:
        errors.err(errors.ERR_VALIDATION, "surge_multiplier must be >= 1.0")

    plan = db.stamp_new({
        "park_id": park["id"],
        "tier": tier,
        "price_cents": price_cents,
        "max_concurrent_holds": max_holds,
        "surge_multiplier": surge,
    })
    db.entitlement_plans[plan["id"]] = plan
    return response.object_response(serialize.view("entitlement_plan", plan), 201)


@bp.get("/parks/<pid>/entitlement-plans")
def list_plans(pid):
    _, role = get_principal()
    require_roles(role, {"ParkAdmin", "GuestApp"})
    park = lookups.get_park(pid)
    records = [p for p in db.entitlement_plans.values() if p["park_id"] == park["id"]]
    return lookups.paginate_and_respond("entitlement_plan", records, response)


# ---------------------------------------------------------------------------
# LightningLanePurchase buy / read / list / redeem
# ---------------------------------------------------------------------------
@bp.post("/lightning-lane-purchases")
def create_purchase():
    user_id, role = get_principal()
    require_roles(role, {"GuestApp"})
    body = vi.get_body()

    park_id = vi.require_str(body, "park_id")
    guest_id = vi.require_str(body, "guest_id")
    ride_id = vi.require_str(body, "ride_id")
    plan_id = vi.require_str(body, "plan_id")

    # existence, left-to-right (priority 3)
    park = lookups.get_park(park_id)
    guest = lookups.get_guest(guest_id)
    ride = lookups.get_ride(ride_id)
    plan = lookups.get_plan(plan_id)

    # ownership (priority 4): acting guest must own this purchase
    if guest["id"] != user_id:
        errors.err(errors.ERR_NOT_RESOURCE_OWNER, "Acting guest does not own this purchase")

    # park scope consistency
    if guest["park_id"] != park["id"]:
        errors.err(errors.ERR_GUEST_PARK_MISMATCH, "Guest belongs to a different park")
    if ride["park_id"] != park["id"]:
        errors.err(errors.ERR_GUEST_PARK_MISMATCH, "Ride belongs to a different park")
    if plan["park_id"] != park["id"]:
        errors.err(errors.ERR_GUEST_PARK_MISMATCH, "Plan belongs to a different park")

    # height (priority 7)
    if guest["height_cm"] < ride["min_height_cm"]:
        errors.err(errors.ERR_HEIGHT_REQUIREMENT_NOT_MET, "Guest height below ride minimum")
    # accessibility (priority 8)
    if guest["uses_wheelchair"] and ride["wheelchair_transfer_required"]:
        errors.err(errors.ERR_ACCESSIBILITY_BLOCKED, "Guest cannot transfer for this ride")
    # hold ceiling (priority 12)
    if domain.active_ll_hold_count(guest["id"]) >= plan["max_concurrent_holds"]:
        errors.err(errors.ERR_HOLD_LIMIT_REACHED, "Guest at the plan's hold ceiling")

    charged = domain.compute_lightning_lane_price(ride, plan)

    purchase = db.stamp_new({
        "park_id": park["id"],
        "guest_id": guest["id"],
        "ride_id": ride["id"],
        "plan_id": plan["id"],
        "charged_cents": charged,
        "hold_status": "ACTIVE",
    })
    db.lightning_lane_purchases[purchase["id"]] = purchase
    return response.object_response(serialize.view("lightning_lane_purchase", purchase), 201)


@bp.get("/lightning-lane-purchases")
def list_purchases():
    _, role = get_principal()
    require_roles(role, {"ParkAdmin", "RideOperator", "GuestApp"})
    park_id = request.args.get("park_id")
    guest_id = request.args.get("guest_id")
    ride_id = request.args.get("ride_id")
    plan_id = request.args.get("plan_id")
    records = list(db.lightning_lane_purchases.values())
    if park_id is not None:
        records = [p for p in records if p["park_id"] == park_id]
    if guest_id is not None:
        records = [p for p in records if p["guest_id"] == guest_id]
    if ride_id is not None:
        records = [p for p in records if p["ride_id"] == ride_id]
    if plan_id is not None:
        records = [p for p in records if p["plan_id"] == plan_id]
    return lookups.paginate_and_respond("lightning_lane_purchase", records, response)


@bp.get("/lightning-lane-purchases/<purchase_id>")
def read_purchase(purchase_id):
    _, role = get_principal()
    require_roles(role, {"ParkAdmin", "RideOperator", "GuestApp"})
    purchase = lookups.get_purchase(purchase_id)
    return response.object_response(serialize.view("lightning_lane_purchase", purchase), 200)


@bp.post("/lightning-lane-purchases/<purchase_id>/redeem")
def redeem_purchase(purchase_id):
    _, role = get_principal()
    require_roles(role, {"RideOperator"})
    purchase = lookups.get_purchase(purchase_id)
    ride = db.rides.get(purchase["ride_id"])

    # state (priority 5): purchase ACTIVE and parent ride OPEN
    if purchase["hold_status"] != "ACTIVE":
        errors.err(errors.ERR_INVALID_STATE, "Purchase is not ACTIVE")
    if ride is None or ride["operational_status"] != "OPEN":
        errors.err(errors.ERR_INVALID_STATE, "Parent ride is not OPEN")

    purchase["hold_status"] = "CONSUMED"
    db.touch(purchase)
    return response.object_response(serialize.view("lightning_lane_purchase", purchase), 200)
