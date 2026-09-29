"""Road testing, derived verdicts and the four-hop failure cascade (PRD 3.6)."""
from flask import Blueprint

import errors
import lookups
import validators as v
from db import db, new_id, public, stamp_new, touch
from middleware import actor, endpoint
from response import created, ok
from services import calc, rollups

bp = Blueprint("roadtests", __name__)

PROTOCOLS = ("STANDARD_20MI", "LOADED_50MI", "BRAKE_FADE")
BOOKABLE_BUILD_STATES = ("SYSTEMS_INSTALLED", "SYSTEMS_REWORK", "ROAD_TEST_PASSED",
                         "LABELED", "RELEASED_TO_STOCK", "ALLOCATED")


def _overlaps(lane_id, start, end):
    """Lane windows are CLOSED and carry no buffer; only SCHEDULED tests occupy."""
    count = 0
    for test in rollups.road_tests_of_lane(lane_id):
        if test["status"] != "SCHEDULED":
            continue
        if test["_window_start"] <= end and start <= test["_window_end"]:
            count += 1
    return count


@bp.route("/trailer-units/<unit_id>/road-tests", methods=["POST"])
@endpoint(["QualityInspector"])
def book_road_test(unit_id):
    unit = lookups.unit_or_404(unit_id)
    data = v.body()
    lane = lookups.lane_or_404(v.req_id(data, "lane_id"))
    start_raw, start_dt = v.req_dt(data, "window_start_at")
    end_raw, end_dt = v.req_dt(data, "window_end_at")
    protocol_code = v.req_enum(data, "protocol_code", PROTOCOLS)
    if end_dt <= start_dt:
        raise errors.invalid("window_end_at must be strictly after window_start_at")

    if unit["build_status"] not in BOOKABLE_BUILD_STATES:
        raise errors.ApiError("ERR_UNIT_BUILD_STATE_INVALID", 409,
                              "A trailer in build_status %s may not be booked for a road test"
                              % unit["build_status"])
    if unit["compliance_status"] != "FULLY_COMPLIANT":
        raise errors.ApiError("ERR_UNIT_NOT_COMPLIANT", 422,
                              "A trailer in compliance_status %s may not be road tested"
                              % unit["compliance_status"])
    if _overlaps(lane["id"], start_dt, end_dt) >= lane["max_concurrent_tests"]:
        raise errors.ApiError("ERR_LANE_CAPACITY_EXCEEDED", 409,
                              "Lane %s is already at its concurrent-test capacity for that window"
                              % lane["lane_code"])

    row = {
        "id": new_id(),
        "unit_id": unit["id"],
        "lane_id": lane["id"],
        "window_start_at": start_raw,
        "window_end_at": end_raw,
        "protocol_code": protocol_code,
        "brake_stop_distance_ft": None,
        "lighting_check_passed": None,
        "status": "SCHEDULED",
        "result_notes": None,
        "inspector_user_id": None,
        "_window_start": start_dt,
        "_window_end": end_dt,
    }
    stamp_new(row)
    db.road_tests[row["id"]] = row
    unit["build_status"] = "ROAD_TEST_PENDING"
    touch(unit)
    return created(public(row))


@bp.route("/road-tests/<test_id>", methods=["GET"])
@endpoint(["QualityInspector", "AssemblyTech", "CertificationOfficer", "PlantEngineer"])
def get_road_test(test_id):
    return ok(public(lookups.road_test_or_404(test_id)))


def _void_issued_label(unit, reason):
    label = rollups.issued_label(unit["id"])
    if label is None:
        return None
    label["status"] = "VOIDED"
    label["voided_reason"] = reason
    touch(label)
    unit["vin"] = None
    touch(unit)
    return label


def _release_allocation(unit):
    """Hops two and three of the failed-road-test cascade."""
    order = db.orders.get(unit.get("dealer_order_id"))
    if order is None or order["status"] != "ALLOCATED":
        return None
    order["status"] = "PENDING"
    order["allocated_unit_id"] = None
    if order["floor_plan_status"] == "DRAWN":
        order["floor_plan_status"] = "RELEASED"
    touch(order)
    unit["dealer_order_id"] = None
    touch(unit)
    rollups.recompute_dealer(db.dealers.get(order["dealer_id"]))
    return order


@bp.route("/road-tests/<test_id>/result", methods=["POST"])
@endpoint(["QualityInspector"])
def record_road_test_result(test_id):
    test = lookups.road_test_or_404(test_id)
    data = v.body()
    distance = v.req_num(data, "brake_stop_distance_ft", minimum=0)
    lighting_passed = v.req_bool(data, "lighting_check_passed")
    notes = v.opt_str(data, "result_notes", max_len=1000)

    if test["status"] != "SCHEDULED":
        raise errors.ApiError("ERR_ROAD_TEST_ALREADY_RESULTED", 409,
                              "Road test %s already carries status %s"
                              % (test["id"], test["status"]))
    unit = db.units.get(test["unit_id"])
    if unit is not None and unit["build_status"] != "ROAD_TEST_PENDING":
        raise errors.ApiError("ERR_UNIT_BUILD_STATE_INVALID", 409,
                              "A trailer in build_status %s may not be resulted"
                              % unit["build_status"])

    passed = (calc.dec(distance) <= calc.ROAD_TEST_MAX_STOP_FT) and lighting_passed is True
    test["brake_stop_distance_ft"] = calc.num(calc.dec(distance))
    test["lighting_check_passed"] = lighting_passed
    test["result_notes"] = notes
    test["inspector_user_id"] = actor()
    test["status"] = "PASSED" if passed else "FAILED"
    touch(test)

    if passed:
        unit["build_status"] = "ROAD_TEST_PASSED"
        touch(unit)
    else:
        unit["build_status"] = "SYSTEMS_REWORK"
        unit["compliance_status"] = "NON_COMPLIANT"
        rollups.recompute_rework_cycle_count(unit)
        touch(unit)
        _void_issued_label(unit, "ROAD_TEST_FAILED")
        _release_allocation(unit)
    return ok(public(test))
