"""Unit reads plus every write that hangs off a unit."""
from flask import Blueprint

import db
import validation as v
from errors import fail, invalid_state
from middleware import (
    ALL_ROLES,
    ROLE_INSPECTOR,
    ROLE_MANAGER,
    ROLE_SURVEYOR,
    ROLE_TECH,
    authenticate,
)
from response import list_response, object_response
from services import calculations as calc
from services import serializers as ser
from services import state

bp = Blueprint("vehicles", __name__)


# --------------------------------------------------------------------- reads
@bp.route("/vpc/vehicles/<vehicle_id>", methods=["GET"])
def read_vehicle(vehicle_id):
    authenticate(ALL_ROLES)
    vehicle = db.must_get("vehicles", vehicle_id)
    return object_response(ser.vehicle(vehicle))


@bp.route("/vpc/vehicles", methods=["GET"])
def list_vehicles():
    authenticate(ALL_ROLES)
    center_id = v.query_filter("processing_center_id")
    vessel_id = v.query_filter("vessel_id")
    hold_id = v.query_filter("blocking_hold_order_id")
    model_line = v.query_filter("model_line")
    processing_status = v.query_filter("processing_status")
    damage_status = v.query_filter("damage_status")
    yard_presence = v.query_filter("yard_presence")
    blocked = v.query_bool("stop_ship_blocked")
    vin = v.query_filter("vin")
    records = db.ordered(db.vehicles)
    if center_id is not None:
        records = [r for r in records if r["processing_center_id"] == center_id]
    if vessel_id is not None:
        records = [r for r in records if r["vessel_id"] == vessel_id]
    if hold_id is not None:
        records = [r for r in records if r["blocking_hold_order_id"] == hold_id]
    if model_line is not None:
        records = [r for r in records if r["model_line"] == model_line]
    if processing_status is not None:
        records = [r for r in records if r["processing_status"] == processing_status]
    if damage_status is not None:
        records = [r for r in records if r["damage_status"] == damage_status]
    if yard_presence is not None:
        records = [r for r in records if r["yard_presence"] == yard_presence]
    if blocked is not None:
        records = [r for r in records if r["stop_ship_blocked"] is blocked]
    if vin is not None:
        records = [r for r in records if r["vin"] == vin]
    items, limit, offset, total = v.paginate(records, ser.vehicle)
    return list_response(items, limit, offset, total)


# ------------------------------------------------- preparation to shipping
@bp.route("/vpc/vehicles/<vehicle_id>/prep-complete", methods=["POST"])
def prep_complete(vehicle_id):
    authenticate([ROLE_INSPECTOR])
    vehicle = db.must_get("vehicles", vehicle_id)

    if vehicle["processing_status"] != "INSPECTION_PASSED":
        invalid_state("preparation is only available from INSPECTION_PASSED")

    # Band 12 outranks band 13, which outranks band 18.
    if vehicle["damage_status"] not in ("NONE", "REPAIRED"):
        fail("ERR_VEHICLE_DAMAGE_BLOCKED", "the unit still carries open damage")
    if vehicle["claim_mandatory"] and not state.claims_of_vehicle(vehicle["id"]):
        fail("ERR_CLAIM_REQUIRED", "a carrier claim is mandatory for this unit")
    vessel = db.vessels.get(vehicle["vessel_id"])
    if vessel is None or vessel["discharge_status"] != "DISCHARGE_COMPLETE":
        fail("ERR_VESSEL_DISCHARGE_INCOMPLETE", "the discharging voyage is not closed yet")

    vehicle["processing_status"] = "SHIPPING_READY"
    db.touch(vehicle)
    return object_response(ser.vehicle(vehicle))


# ------------------------------------------------------------ damage surveys
@bp.route("/vpc/vehicles/<vehicle_id>/damage-surveys", methods=["POST"])
def create_survey(vehicle_id):
    user_id, _role = authenticate([ROLE_SURVEYOR])
    vehicle = db.must_get("vehicles", vehicle_id)
    body = v.body()
    line_items = v.req_line_items(body)

    record = db.base_record()
    record.update(
        {
            "vehicle_id": vehicle["id"],
            "surveyed_by_user_id": user_id,
            "line_items": line_items,
            "line_count": len(line_items),
            "severity_index": None,
            "claimed_amount_cents": None,
            "status": "DRAFT",
        }
    )
    db.surveys[record["id"]] = record
    return object_response(ser.survey(record), 201)


# ------------------------------------------------------------ repair orders
@bp.route("/vpc/vehicles/<vehicle_id>/repair-orders", methods=["POST"])
def create_repair_order(vehicle_id):
    user_id, _role = authenticate([ROLE_SURVEYOR])
    vehicle = db.must_get("vehicles", vehicle_id)
    body = v.body()

    claim = None
    if v.present(body, "carrier_claim_id"):
        claim = db.claims.get(body["carrier_claim_id"])
        if claim is None:
            fail("ERR_REFERENCE_NOT_FOUND", "carrier_claim_id does not resolve")

    description = v.req_str(body, "description")
    estimate = v.req_int(body, "estimate_cents", minimum=0)
    tier = calc.repair_authorization_tier(estimate)

    record = db.base_record()
    record.update(
        {
            "vehicle_id": vehicle["id"],
            "carrier_claim_id": claim["id"] if claim is not None else None,
            "description": description,
            "estimate_cents": estimate,
            "actual_cost_cents": None,
            "authorization_tier": tier,
            "estimated_by_user_id": user_id,
            "authorized_by_user_id": user_id if tier == "AUTO" else None,
            "status": "AUTHORIZED" if tier == "AUTO" else "ESCALATED",
        }
    )
    db.repair_orders[record["id"]] = record

    if tier == "AUTO" and vehicle["damage_status"] == "SURVEY_DAMAGE_OPEN":
        vehicle["damage_status"] = "REPAIR_AUTHORIZED"
        db.touch(vehicle)
    return object_response(ser.repair_order(record), 201)


# ---------------------------------------------------- accessory work orders
@bp.route("/vpc/vehicles/<vehicle_id>/accessory-work-orders", methods=["POST"])
def create_work_order(vehicle_id):
    authenticate([ROLE_TECH])
    vehicle = db.must_get("vehicles", vehicle_id)
    body = v.body()

    kit = None
    if v.present(body, "accessory_kit_id"):
        kit = db.kits.get(body["accessory_kit_id"])
        if kit is None:
            fail("ERR_REFERENCE_NOT_FOUND", "accessory_kit_id does not resolve")

    v.req_str(body, "accessory_kit_id")
    qty = v.req_int(body, "qty", minimum=1)

    record = db.base_record()
    record.update(
        {
            "vehicle_id": vehicle["id"],
            "accessory_kit_id": kit["id"],
            "qty": qty,
            "billed_cents": 0,
            "installed_by_user_id": None,
            "reopen_count": 0,
            "status": "PLANNED",
        }
    )
    db.work_orders[record["id"]] = record
    return object_response(ser.work_order(record), 201)


# ------------------------------------------------------- quality inspections
@bp.route("/vpc/vehicles/<vehicle_id>/quality-inspections", methods=["POST"])
def create_inspection(vehicle_id):
    user_id, _role = authenticate([ROLE_INSPECTOR])
    vehicle = db.must_get("vehicles", vehicle_id)

    # SoD 1: an installer of this unit's accessories may not inspect it.
    for order in db.work_orders.values():
        if order["vehicle_id"] != vehicle["id"]:
            continue
        if order["installed_by_user_id"] != user_id:
            continue
        if order["status"] == "INSTALLED" or (
            order["status"] == "KITTED" and order["reopen_count"] > 0
        ):
            fail(
                "ERR_SEGREGATION_OF_DUTIES",
                "an operator who installed accessories on this unit may not inspect it",
            )

    record = db.base_record()
    record.update(
        {
            "vehicle_id": vehicle["id"],
            "inspector_user_id": user_id,
            "outcome": None,
            "defect_count": None,
            "status": "OPEN",
        }
    )
    db.inspections[record["id"]] = record
    return object_response(ser.inspection(record), 201)


# ------------------------------------------------------------- allocations
@bp.route("/vpc/vehicles/<vehicle_id>/allocations", methods=["POST"])
def allocate(vehicle_id):
    authenticate([ROLE_MANAGER])
    vehicle = db.must_get("vehicles", vehicle_id)
    body = v.body()

    dealer = None
    if v.present(body, "dealer_id"):
        dealer = db.dealers.get(body["dealer_id"])
        if dealer is None:
            fail("ERR_REFERENCE_NOT_FOUND", "dealer_id does not resolve")

    v.req_str(body, "dealer_id")
    window_start, window_end = v.req_interval(body, "pickup_window_start", "pickup_window_end")
    expected_version = v.req_int(body, "expected_vehicle_version")

    # Band 7: optimistic concurrency on the unit.
    if expected_version != vehicle["version"]:
        fail(
            "ERR_STALE_VEHICLE_VERSION",
            "expected_vehicle_version %s does not match the unit's current version %s"
            % (expected_version, vehicle["version"]),
        )

    # Band 8: state legality on both the unit and any order it already holds.
    prior = state.active_release_order(vehicle["id"])
    if vehicle["processing_status"] == "SHIPPING_READY":
        pass
    elif vehicle["processing_status"] == "ALLOCATED":
        if prior is None or prior["status"] != "ALLOCATED":
            invalid_state("a released order cannot be superseded")
    else:
        invalid_state("allocation is only available from SHIPPING_READY or ALLOCATED")
    if prior is not None and prior["status"] != "ALLOCATED":
        invalid_state("a released order cannot be superseded")

    # Band 11: stop-ship blocking.
    if vehicle["stop_ship_blocked"] or state.open_holds_covering(vehicle):
        fail("ERR_VEHICLE_STOP_SHIP_BLOCKED", "an open hold covers this unit")

    # Band 23: carrier eligibility, then band 25: the consignee's quota.
    route_zone = dealer["route_zone"]
    carrier = state.select_carrier(route_zone)
    if carrier is None:
        fail("ERR_NO_ELIGIBLE_CARRIER", "no active carrier serves zone %s with a free slot" % route_zone)
    state.recompute_dealer(dealer)
    if dealer["open_allocation_count"] >= dealer["allocation_quota"]:
        fail("ERR_DEALER_QUOTA_EXCEEDED", "the consignee has no allocation quota left")

    allocated_at = db.clock_now()
    record = db.base_record()
    record.update(
        {
            "vehicle_id": vehicle["id"],
            "dealer_id": dealer["id"],
            "truck_carrier_id": carrier["id"],
            "superseded_release_order_id": prior["id"] if prior is not None else None,
            "cancelled_by_hold_order_id": None,
            "pickup_window_start": window_start,
            "pickup_window_end": window_end,
            "route_zone": route_zone,
            "base_linehaul_cents": 0,
            "fuel_surcharge_cents": 0,
            "zone_accessorial_cents": 0,
            "gross_freight_cents": 0,
            "freight_discount_cents": 0,
            "freight_total_cents": 0,
            "allocated_at": allocated_at,
            "dispatched_at": None,
            "gated_out_at": None,
            "status": "ALLOCATED",
        }
    )
    db.release_orders[record["id"]] = record

    prior_carrier = None
    prior_dealer = None
    if prior is not None:
        prior["status"] = "CANCELLED"
        db.touch(prior)
        prior_carrier = db.carriers.get(prior["truck_carrier_id"])
        prior_dealer = db.dealers.get(prior["dealer_id"])

    state.recompute_carrier(carrier)
    if prior_carrier is not None and prior_carrier is not carrier:
        state.recompute_carrier(prior_carrier)
    state.recompute_dealer(dealer)
    if prior_dealer is not None and prior_dealer is not dealer:
        state.recompute_dealer(prior_dealer)

    center = state.center_of_vehicle(vehicle)
    vehicle["processing_status"] = "ALLOCATED"
    if center is not None:
        vehicle["storage_charge_provisional_cents"] = state.stamp_provisional_storage(
            vehicle, center, allocated_at
        )
    db.touch(vehicle)
    if center is not None:
        state.recompute_center(center)
    return object_response(ser.release_order(record), 201)
