"""Capacity and cycle-life tests: chamber power allocation and result recording."""
from decimal import Decimal

from flask import Blueprint, g

from authz import (
    PLANT_ADMIN,
    PRODUCTION_SUPERVISOR,
    QUALITY_INSPECTOR,
    WARRANTY_ADMINISTRATOR,
    endpoint,
)
from errors import ApiError
from helpers import apply_filters, lookup, paginated
from response import object_response
from store import db
from services.lot_service import capacity_verdict, quarantine_cascade, recompute_lot_yield

bp = Blueprint("tests", __name__)

TEST_READERS = [PLANT_ADMIN, PRODUCTION_SUPERVISOR, QUALITY_INSPECTOR, WARRANTY_ADMINISTRATOR]

CREATE_SPEC = {
    "assembly_id": {"type": "id", "required": True},
    "chamber_id": {"type": "id", "required": True},
    "test_type": {"type": "enum", "required": True, "values": ["CAPACITY", "CYCLE_LIFE"]},
    "scheduled_start_at": {"type": "datetime", "required": True},
    "scheduled_end_at": {"type": "datetime", "required": True},
    "draw_kw": {"type": "number", "required": True, "gt": 0},
}

RESULT_SPEC = {
    "measured_capacity_ah": {"type": "number", "required": True, "gt": 0},
    "cycles_completed": {"type": "int", "gte": 0},
}

TEST_FILTERS = {
    "assembly_id": "assembly_id",
    "chamber_id": "chamber_id",
    "recorded_by_worker_id": "recorded_by_worker_id",
    "test_type": "test_type",
    "test_state": "test_state",
    "result": "result",
}
DEFAULT_ORDER = [("scheduled_start_at", "asc"), ("created_at", "asc")]


def _peak_draw(chamber, start, end, requested):
    """Half-open interval sweep: the cap binds at every covered instant."""
    overlapping = [
        t
        for t in db.capacity_tests.values()
        if t.get("chamber_id") == chamber["id"]
        and t.get("test_state") == "SCHEDULED"
        and t["scheduled_start_at"] < end
        and t["scheduled_end_at"] > start
    ]
    points = [start]
    for test in overlapping:
        if test["scheduled_start_at"] > start:
            points.append(test["scheduled_start_at"])
    peak = requested
    for point in points:
        total = requested
        for test in overlapping:
            if test["scheduled_start_at"] <= point < test["scheduled_end_at"]:
                total += test["draw_kw"]
        if total > peak:
            peak = total
    return peak


@bp.post("/capacity-tests")
@endpoint([QUALITY_INSPECTOR], body=CREATE_SPEC)
def create_test():
    payload = g.body
    assembly = lookup("battery_assemblies", payload["assembly_id"])
    chamber = lookup("test_chambers", payload["chamber_id"], "ERR_TEST_CHAMBER_NOT_FOUND")
    lot = db.production_lots.get(assembly["lot_id"])
    if lot is None or lot["process_state"] not in ("ASSEMBLY", "LOT_TESTING"):
        raise ApiError(
            "ERR_LOT_STATE_INVALID",
            "A test may only be booked while the lot is in ASSEMBLY or LOT_TESTING",
        )
    if lot.get("env_hold_status") == "HELD":
        raise ApiError("ERR_LOT_ENV_HELD", "The lot is under an environmental hold")
    if assembly.get("certification_status") != "CERTIFIED":
        raise ApiError("ERR_ASSEMBLY_NOT_CERTIFIED", "The assembly is not CERTIFIED")
    if chamber["plant_id"] != lot["plant_id"]:
        raise ApiError(
            "ERR_PLANT_SCOPE_MISMATCH",
            "The chamber belongs to a different plant than the assembly's lot",
        )
    if chamber.get("chamber_status") != "AVAILABLE":
        raise ApiError("ERR_CHAMBER_UNAVAILABLE", "The chamber is in MAINTENANCE")
    start = payload["scheduled_start_at"]
    end = payload["scheduled_end_at"]
    if not end > start:
        raise ApiError(
            "ERR_WINDOW_INVALID", "scheduled_end_at must be strictly after scheduled_start_at"
        )
    if _peak_draw(chamber, start, end, payload["draw_kw"]) > chamber["power_cap_kw"]:
        raise ApiError(
            "ERR_CHAMBER_CAPACITY_EXCEEDED",
            "The aggregate simultaneous draw would exceed the chamber's power cap",
        )
    record = {
        "assembly_id": assembly["id"],
        "chamber_id": chamber["id"],
        "test_type": payload["test_type"],
        "scheduled_start_at": start,
        "scheduled_end_at": end,
        "draw_kw": payload["draw_kw"],
        "test_state": "SCHEDULED",
        "measured_capacity_ah": None,
        "cycles_completed": None,
        "result": None,
        "yield_pct": None,
        "recorded_by_worker_id": None,
    }
    db.insert("capacity_tests", record)
    return object_response(record, 201)


@bp.get("/capacity-tests")
@endpoint(TEST_READERS, paginated=True)
def list_tests():
    return paginated(apply_filters(db.rows("capacity_tests"), TEST_FILTERS), DEFAULT_ORDER)


@bp.get("/capacity-tests/<test_id>")
@endpoint(TEST_READERS)
def read_test(test_id):
    return object_response(lookup("capacity_tests", test_id))


@bp.post("/capacity-tests/<test_id>/record-result")
@endpoint([QUALITY_INSPECTOR], body=RESULT_SPEC)
def record_result(test_id):
    payload = g.body
    test = lookup("capacity_tests", test_id, "ERR_CAPACITY_TEST_NOT_FOUND")
    lot = db.production_lots.get(
        (db.battery_assemblies.get(test["assembly_id"]) or {}).get("lot_id")
    )
    if test["test_state"] != "SCHEDULED":
        raise ApiError("ERR_CAPACITY_TEST_STATE_INVALID", "Only a SCHEDULED test may be recorded")
    if db.now() < test["scheduled_end_at"]:
        raise ApiError(
            "ERR_CAPACITY_TEST_STATE_INVALID",
            "The test window has not closed on the logical clock yet",
        )
    if lot is None or lot["process_state"] != "LOT_TESTING":
        raise ApiError(
            "ERR_CAPACITY_TEST_STATE_INVALID",
            "Results may only be recorded while the lot is in LOT_TESTING",
        )
    supplied = "cycles_completed" in payload
    if test["test_type"] == "CYCLE_LIFE" and not supplied:
        raise ApiError(
            "ERR_CYCLE_LIFE_SAMPLE_MISSING", "cycles_completed is required for a CYCLE_LIFE test"
        )
    if test["test_type"] == "CAPACITY" and supplied:
        raise ApiError(
            "ERR_CYCLE_LIFE_SAMPLE_MISSING", "cycles_completed must be omitted for a CAPACITY test"
        )
    if lot.get("env_hold_status") == "HELD":
        raise ApiError("ERR_LOT_ENV_HELD", "The lot is under an environmental hold")
    design = db.cell_designs.get(lot["cell_design_id"])
    test["measured_capacity_ah"] = payload["measured_capacity_ah"]
    test["cycles_completed"] = payload.get("cycles_completed")
    yield_pct, result = capacity_verdict(test, design)
    test["test_state"] = "COMPLETED"
    test["yield_pct"] = yield_pct
    test["result"] = result
    test["recorded_by_worker_id"] = g.actor["id"]
    db.touch(test)
    lot["last_test_recorded_by_worker_id"] = g.actor["id"]
    lot["completed_test_count"] = lot.get("completed_test_count", 0) + 1
    if result == "FAIL":
        lot["failed_test_count"] = lot.get("failed_test_count", 0) + 1
    elif test["test_type"] == "CYCLE_LIFE":
        lot["passed_cycle_life_count"] = lot.get("passed_cycle_life_count", 0) + 1
    if lot["failed_test_count"] > (lot.get("acceptance_number") or 0):
        quarantine_cascade(lot)
    recompute_lot_yield(lot)
    db.touch(lot)
    return object_response(test)
