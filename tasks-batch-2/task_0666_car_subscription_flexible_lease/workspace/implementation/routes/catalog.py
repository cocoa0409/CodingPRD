"""Catalog & fleet/vehicle routes (PRD §3.1, §3.2, §3.7)."""
from flask import Blueprint

import errors
from db import db, stamp_create, touch
from middleware import get_identity, require_roles, parse_pagination
from response import object_response, array_response
from services import calc, serialize
from services import common

bp = Blueprint("catalog", __name__)

PLAN_TIERS = {"ESSENTIAL", "PLUS", "PREMIUM"}
HISTORY_FLAGS = {"CLEAN", "MINOR", "SEVERE"}


# --------------------------- SubscriptionPlan ---------------------------
@bp.route("/subscription-plans", methods=["POST"])
def create_plan():
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin"})  # exclusive (PRD §3.1)
    body = common.get_body()

    tier = common.require_enum(body, "tier", PLAN_TIERS)
    monthly_fee = common.require_int(body, "monthly_fee_cents", min_value=1)
    included_miles = common.require_int(body, "included_miles_per_cycle", min_value=0)
    free_buffer = common.optional_int(body, "free_buffer_miles", default=0, min_value=0)
    t1 = common.require_int(body, "overage_tier1_rate_cents", min_value=0)
    t2 = common.require_int(body, "overage_tier2_rate_cents", min_value=0)
    if t2 < t1:
        raise errors.invalid_request("overage_tier2_rate_cents must be >= overage_tier1_rate_cents.")
    included_swaps = common.optional_int(body, "included_swaps_per_term", default=0, min_value=0)
    min_term = common.require_int(body, "min_term_months", min_value=1)
    deposit_base = common.require_int(body, "deposit_base_cents", min_value=0)

    # tier unique among ACTIVE plans (priority 13, ERR_DUPLICATE_VALUE).
    for p in db.subscription_plans.values():
        if p["status"] == "ACTIVE" and p["tier"] == tier:
            raise errors.duplicate_value("Plan tier already exists among ACTIVE plans.")

    rec = {
        "tier": tier,
        "monthly_fee_cents": monthly_fee,
        "included_miles_per_cycle": included_miles,
        "free_buffer_miles": free_buffer,
        "overage_tier1_rate_cents": t1,
        "overage_tier2_rate_cents": t2,
        "included_swaps_per_term": included_swaps,
        "min_term_months": min_term,
        "deposit_base_cents": deposit_base,
        "status": "ACTIVE",  # system-managed default (PRD §3.1)
    }
    stamp_create(rec)
    db.subscription_plans[rec["id"]] = rec
    return object_response(serialize.serialize_plan(rec), 201)


@bp.route("/subscription-plans/<pid>", methods=["GET"])
def get_plan(pid):
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "FleetOperator", "BillingAdmin", "Member"})
    rec = common.resolve(db.subscription_plans, pid)
    return object_response(serialize.serialize_plan(rec))


@bp.route("/subscription-plans", methods=["GET"])
def list_plans():
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "FleetOperator", "BillingAdmin", "Member"})
    limit, offset = parse_pagination()
    from flask import request
    records = list(db.subscription_plans.values())
    records = common.filter_equals(records, "status", request.args.get("status"))
    page, total = common.paginate_sorted(records, limit, offset)
    return array_response([serialize.serialize_plan(r) for r in page], limit, offset, total)


# --------------------------- Fleet ---------------------------
@bp.route("/fleets", methods=["POST"])
def create_fleet():
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin"})  # exclusive (PRD §3.1)
    body = common.get_body()
    name = common.require_str(body, "name")
    region = common.require_str(body, "region_code")
    rec = {
        "name": name,
        "region_code": region,
        # derived counts initialize to 0 (PRD §3.1).
        "total_vehicles": 0,
        "in_use_count": 0,
        "utilization_pct": 0,
    }
    stamp_create(rec)
    db.fleets[rec["id"]] = rec
    return object_response(serialize.serialize_fleet(rec), 201)


@bp.route("/fleets/<fid>", methods=["GET"])
def get_fleet(fid):
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "FleetOperator", "BillingAdmin"})
    rec = common.resolve(db.fleets, fid)
    return object_response(serialize.serialize_fleet(rec))


@bp.route("/fleets", methods=["GET"])
def list_fleets():
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "FleetOperator", "BillingAdmin"})
    limit, offset = parse_pagination()
    from flask import request
    records = list(db.fleets.values())
    records = common.filter_equals(records, "region_code", request.args.get("region_code"))
    page, total = common.paginate_sorted(records, limit, offset)
    return array_response([serialize.serialize_fleet(r) for r in page], limit, offset, total)


@bp.route("/fleets/<fid>/vehicles", methods=["GET"])
def list_fleet_vehicles(fid):
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "FleetOperator", "BillingAdmin"})
    common.resolve(db.fleets, fid)
    limit, offset = parse_pagination()
    from flask import request
    records = [v for v in db.vehicles.values() if v["fleet_id"] == fid]
    records = common.filter_equals(records, "status", request.args.get("status"))
    page, total = common.paginate_sorted(records, limit, offset)
    return array_response([serialize.serialize_vehicle(r) for r in page], limit, offset, total)


@bp.route("/fleets/<fid>/utilization", methods=["GET"])
def fleet_utilization(fid):
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "FleetOperator", "BillingAdmin"})
    fleet = common.resolve(db.fleets, fid)
    from flask import request
    basis = request.args.get("basis", "RESERVATION_INCLUSIVE")
    total, in_use_reserved = serialize._fleet_counts(fid)
    if basis == "ASSIGNED_ONLY":
        in_use = sum(1 for v in db.vehicles.values()
                     if v["fleet_id"] == fid and v["status"] == "ASSIGNED")
    else:
        in_use = in_use_reserved
    pct = calc.utilization_pct(in_use, total)
    return object_response({
        "basis": basis,
        "total_vehicles": total,
        "in_use_count": in_use,
        "utilization_pct": pct,
    })


# --------------------------- Vehicle ---------------------------
@bp.route("/vehicles", methods=["POST"])
def create_vehicle():
    _, role = get_identity()
    require_roles(role, {"FleetOperator", "PlatformAdmin"})  # shared (PRD §3.2)
    body = common.get_body()
    fleet_id = common.require_str(body, "fleet_id")
    plan_id = common.require_str(body, "plan_id")
    vin = common.require_str(body, "vin")
    model_label = common.require_str(body, "model_label")
    odometer = common.require_int(body, "odometer_miles", min_value=0)

    # Existence of FK references (priority 4) before uniqueness (priority 13).
    common.resolve(db.fleets, fleet_id)
    common.resolve(db.subscription_plans, plan_id)

    for v in db.vehicles.values():
        if v["vin"] == vin:
            raise errors.duplicate_value("Vehicle VIN already exists.")

    rec = {
        "fleet_id": fleet_id,
        "plan_id": plan_id,
        "vin": vin,
        "model_label": model_label,
        "odometer_miles": odometer,
        "status": "AVAILABLE",            # default (PRD §3.2)
        "active_subscription_id": None,   # default (PRD §3.2)
    }
    stamp_create(rec)
    db.vehicles[rec["id"]] = rec
    # Adding a vehicle recomputes the owning fleet (PRD §3.2).
    common.recompute_fleet(fleet_id)
    return object_response(serialize.serialize_vehicle(rec), 201)


@bp.route("/vehicles/<vid>", methods=["GET"])
def get_vehicle(vid):
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "FleetOperator", "BillingAdmin", "Member"})
    rec = common.resolve(db.vehicles, vid)
    return object_response(serialize.serialize_vehicle(rec))


@bp.route("/vehicles", methods=["GET"])
def list_vehicles():
    _, role = get_identity()
    require_roles(role, {"PlatformAdmin", "FleetOperator", "BillingAdmin"})
    limit, offset = parse_pagination()
    from flask import request
    records = list(db.vehicles.values())
    records = common.filter_equals(records, "fleet_id", request.args.get("fleet_id"))
    records = common.filter_equals(records, "plan_id", request.args.get("plan_id"))
    records = common.filter_equals(records, "active_subscription_id",
                                   request.args.get("active_subscription_id"))
    records = common.filter_equals(records, "status", request.args.get("status"))
    page, total = common.paginate_sorted(records, limit, offset)
    return array_response([serialize.serialize_vehicle(r) for r in page], limit, offset, total)


@bp.route("/vehicles/<vid>/maintenance", methods=["POST"])
def vehicle_maintenance(vid):
    _, role = get_identity()
    require_roles(role, {"FleetOperator"})  # exclusive (PRD §3.2)
    v = common.resolve(db.vehicles, vid)
    # state precondition (priority 6): ASSIGNED -> MAINTENANCE.
    if v["status"] != "ASSIGNED":
        raise errors.invalid_state("Vehicle must be ASSIGNED to enter MAINTENANCE.")
    # no overlapping non-terminal delivery slot conflict per buffer geometry (scaffold).
    _check_no_maintenance_slot_conflict(v)
    v["status"] = "MAINTENANCE"
    touch(v)
    # MAINTENANCE is not in_use: in_use_count-1, utilization recomputed (PRD §3.2).
    common.recompute_fleet(v["fleet_id"])
    return object_response(serialize.serialize_vehicle(v))


@bp.route("/vehicles/<vid>/maintenance-complete", methods=["POST"])
def vehicle_maintenance_complete(vid):
    _, role = get_identity()
    require_roles(role, {"FleetOperator"})  # exclusive (PRD §3.2)
    v = common.resolve(db.vehicles, vid)
    if v["status"] != "MAINTENANCE":
        raise errors.invalid_state("Vehicle must be in MAINTENANCE to complete.")
    v["status"] = "AVAILABLE"
    touch(v)
    common.recompute_fleet(v["fleet_id"])
    return object_response(serialize.serialize_vehicle(v))


def _check_no_maintenance_slot_conflict(vehicle):
    """A MAINTENANCE transition is blocked by an overlapping non-terminal (SCHEDULED)
    delivery slot for the vehicle's active subscription (scaffold §1.2 precondition)."""
    sub_id = vehicle.get("active_subscription_id")
    if not sub_id:
        return
    for slot in db.delivery_slots.values():
        if slot["subscription_id"] == sub_id and slot["status"] == "SCHEDULED":
            raise errors.invalid_state(
                "Vehicle has a non-terminal delivery slot; cannot enter MAINTENANCE."
            )
