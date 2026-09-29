"""Quality inspections and the four-link rework cascade (PRD §3.6)."""
from flask import Blueprint

import db
import validation as v
from errors import fail, invalid, invalid_state
from middleware import OPS_ROLES, ROLE_INSPECTOR, authenticate
from response import list_response, object_response
from services import serializers as ser
from services import state

bp = Blueprint("inspections", __name__)

PASSABLE_VEHICLE_STATES = ("SURVEYED", "ACCESSORY_IN_PROGRESS", "INSPECTION_PASSED")


@bp.route("/vpc/quality-inspections/<inspection_id>", methods=["GET"])
def read_inspection(inspection_id):
    authenticate(OPS_ROLES)
    inspection = db.must_get("inspections", inspection_id)
    return object_response(ser.inspection(inspection))


@bp.route("/vpc/quality-inspections", methods=["GET"])
def list_inspections():
    authenticate(OPS_ROLES)
    vehicle_id = v.query_filter("vehicle_id")
    status = v.query_filter("status")
    outcome = v.query_filter("outcome")
    records = db.ordered(db.inspections)
    if vehicle_id is not None:
        records = [r for r in records if r["vehicle_id"] == vehicle_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if outcome is not None:
        records = [r for r in records if r["outcome"] == outcome]
    items, limit, offset, total = v.paginate(records, ser.inspection)
    return list_response(items, limit, offset, total)


@bp.route("/vpc/quality-inspections/<inspection_id>/complete", methods=["POST"])
def complete_inspection(inspection_id):
    authenticate([ROLE_INSPECTOR])
    inspection = db.must_get("inspections", inspection_id)
    body = v.body()
    outcome = v.req_enum(body, "outcome", ("PASS", "FAIL"))
    defect_count = v.req_int(body, "defect_count", minimum=0)
    if outcome == "PASS" and defect_count != 0:
        invalid("a PASS outcome requires a defect_count of exactly 0")
    if outcome == "FAIL" and defect_count < 1:
        invalid("a FAIL outcome requires a defect_count of at least 1")

    if inspection["status"] != "OPEN":
        invalid_state("only an OPEN inspection can be completed")

    vehicle = db.vehicles.get(inspection["vehicle_id"])
    work_orders = [
        w for w in db.ordered(db.work_orders) if w["vehicle_id"] == inspection["vehicle_id"]
    ]

    if outcome == "PASS":
        if vehicle is None or vehicle["processing_status"] not in PASSABLE_VEHICLE_STATES:
            invalid_state("the unit is not in a state that a quality inspection can pass")
        if any(w["status"] == "KITTED" for w in work_orders):
            fail(
                "ERR_ACCESSORY_WORK_OPEN",
                "accessory work is still reserved but not installed on this unit",
            )
        inspection["outcome"] = "PASS"
        inspection["defect_count"] = defect_count
        inspection["status"] = "PASSED"
        db.touch(inspection)
        if vehicle["processing_status"] != "INSPECTION_PASSED":
            vehicle["processing_status"] = "INSPECTION_PASSED"
            db.touch(vehicle)
        return object_response(ser.inspection(inspection))

    # LINK 1: the inspection itself fails.
    inspection["outcome"] = "FAIL"
    inspection["defect_count"] = defect_count
    inspection["status"] = "FAILED"
    db.touch(inspection)

    if vehicle is None:
        return object_response(ser.inspection(inspection))

    # LINK 2: the unit returns to rework (already there in the second FAIL shape).
    if vehicle["processing_status"] == "INSPECTION_PASSED":
        vehicle["processing_status"] = "ACCESSORY_IN_PROGRESS"
    vehicle["rework_cycle_count"] = vehicle["rework_cycle_count"] + 1

    # LINK 3 + LINK 4: reopen installed work in created_at order and restore stock.
    touched_kits = []
    for order in work_orders:
        if order["status"] != "INSTALLED":
            continue
        order["status"] = "KITTED"
        order["reopen_count"] = order["reopen_count"] + 1
        order["billed_cents"] = 0
        db.touch(order)
        kit = db.kits.get(order["accessory_kit_id"])
        if kit is not None:
            kit["on_hand_qty"] = kit["on_hand_qty"] + order["qty"]
            if kit not in touched_kits:
                touched_kits.append(kit)
    for kit in touched_kits:
        state.recompute_kit(kit)

    vehicle["accessory_billed_cents"] = state.vehicle_accessory_billed(vehicle["id"])
    db.touch(vehicle)
    return object_response(ser.inspection(inspection))
