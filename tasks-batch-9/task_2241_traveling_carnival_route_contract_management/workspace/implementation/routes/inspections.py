"""Ride inspections: scheduling against jurisdiction slots and results."""

from flask import Blueprint, request

import calc
import db
import errors
import serializers as ser
import validators as v
from errors import fail, invalid
from middleware import (ROLE_GENERAL_MANAGER, ROLE_JURISDICTION_OFFICER,
                        ROLE_PLATFORM_ADMIN, ROLE_ROUTE_MANAGER,
                        ROLE_SAFETY_OFFICER, ROLE_TICKETING_AUDITOR, require_role)
from response import created, ok, paginate

bp = Blueprint("inspections", __name__)

AUTHORITIES = ("STATE", "THIRD_PARTY")
RESULTS = ("PASS", "FAIL")
INSPECTABLE = ("RESERVED", "COMMITTED", "INSPECTION_HELD")
READ_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_ROUTE_MANAGER, ROLE_GENERAL_MANAGER,
              ROLE_TICKETING_AUDITOR, ROLE_SAFETY_OFFICER,
              ROLE_JURISDICTION_OFFICER)


@bp.post("/inspection-orders")
def create_inspection():
    require_role(ROLE_SAFETY_OFFICER)
    body = v.get_body()
    alloc = v.body_ref(body, "ride_allocation_id", "ride_allocations")
    if alloc is None:
        v.req_str(body, "ride_allocation_id")
    authority = v.req_enum(body, "authority", AUTHORITIES)
    scheduled_raw, scheduled_dt = v.req_dt(body, "scheduled_date")

    if alloc["status"] not in INSPECTABLE:
        fail(errors.ERR_ALLOCATION_STATE_INVALID,
             "Only a RESERVED, COMMITTED or INSPECTION_HELD allocation may be "
             "inspected.")
    stop = calc.stop_of_allocation(alloc)
    jurisdiction = calc.jurisdiction_of(stop) if stop else None
    if jurisdiction is not None:
        capacity = int(jurisdiction["inspection_slot_capacity_per_day"])
        day = db.day_bucket(scheduled_dt)
        if calc.slots_used(jurisdiction["id"], day) >= capacity:
            fail(errors.ERR_INSPECTION_SLOTS_FULL,
                 "The jurisdiction has no inspection slot left on that day.")

    failed = len(calc.inspections_of_allocation(alloc["id"], ("FAILED",)))
    row = db.create(db.store.inspection_orders, {
        "ride_allocation_id": alloc["id"],
        "authority": authority,
        "scheduled_date": scheduled_raw,
        "status": "SCHEDULED",
        "attempt_number": 1 + failed,
        "defect_count": 0,
        "result_recorded_at": None,
    })
    if stop is not None:
        db.touch(stop)
    return created(ser.inspection_order(row))


@bp.get("/ride-allocations/<alloc_id>/inspections")
def list_inspections(alloc_id):
    require_role(*READ_ROLES)
    alloc = v.path_row("ride_allocations", alloc_id)
    rows = calc.inspections_of_allocation(alloc["id"])
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser.inspection_order)


@bp.post("/inspection-orders/<inspection_id>/result")
def record_result(inspection_id):
    require_role(ROLE_JURISDICTION_OFFICER)
    inspection = v.path_row("inspection_orders", inspection_id)
    body = v.get_body()
    result = v.req_enum(body, "result", RESULTS)
    defect_count = v.opt_int(body, "defect_count", 0, minimum=0)
    if result == "FAIL" and defect_count < 1:
        invalid("defect_count must be at least 1 when the result is FAIL.")

    if inspection["status"] != "SCHEDULED":
        fail(errors.ERR_INSPECTION_STATE_INVALID,
             "Only a SCHEDULED inspection may carry a result.")
    alloc = db.store.ride_allocations.get(inspection["ride_allocation_id"])
    if alloc is None or alloc["status"] not in ("COMMITTED", "INSPECTION_HELD"):
        fail(errors.ERR_ALLOCATION_NOT_INSPECTABLE,
             "The allocation is neither COMMITTED nor INSPECTION_HELD.")
    ride = db.store.rides.get(alloc["ride_id"])
    stop = calc.stop_of_allocation(alloc)

    inspection["result_recorded_at"] = db.now_iso()
    if result == "PASS":
        inspection["status"] = "PASSED"
        inspection["defect_count"] = 0
        db.touch(inspection)
        if alloc["status"] == "INSPECTION_HELD" and (
                ride is None or ride["status"] != "OUT_OF_SERVICE"):
            alloc["status"] = "COMMITTED"
            db.touch(alloc)
    else:
        inspection["status"] = "FAILED"
        inspection["defect_count"] = defect_count
        db.touch(inspection)
        if alloc["status"] == "COMMITTED":
            alloc["status"] = "INSPECTION_HELD"
            db.touch(alloc)
        if ride is not None and defect_count >= calc.OUT_OF_SERVICE_DEFECT_THRESHOLD:
            ride["status"] = "OUT_OF_SERVICE"
            db.touch(ride)
    if stop is not None:
        db.touch(stop)
    return ok(ser.inspection_order(inspection))
