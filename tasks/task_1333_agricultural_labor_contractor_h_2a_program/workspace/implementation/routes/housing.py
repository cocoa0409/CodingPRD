"""Housing units, inspections, housing assignments."""

from datetime import timedelta

from flask import Blueprint, request

from calc import d, iso
from common import (ALL_ROLES, ApiError, auth, body, clock_date, created_order,
                    get_or_404, invalid, ok, ok_list, paginate,
                    parse_date_val, req_int, req_str, stamp_immutable,
                    stamp_new, touch)
from services import (ser_housing_assignment, ser_housing_unit,
                      ser_inspection)
from store import db

bp = Blueprint("housing", __name__)


def _unit(rid):
    return get_or_404(db.housing_units, rid, "ERR_HOUSING_UNIT_NOT_FOUND",
                      "housing unit")


@bp.post("/h2a/housing-units")
@auth("ContractorAdmin")
def create_housing_unit():
    b = body()
    grower_id = b.get("grower_id")
    if grower_id is None:
        raise invalid("grower_id is required")
    get_or_404(db.growers, grower_id, "ERR_GROWER_NOT_FOUND", "grower")
    name = req_str(b, "name")
    capacity = req_int(b, "capacity")
    if capacity < 1:
        raise invalid("capacity must be >= 1")
    rec = {
        "grower_id": grower_id,
        "name": name,
        "capacity": capacity,
        "inspection_status": "UNINSPECTED",
        "certified_on": None,
    }
    stamp_new(rec)
    db.housing_units[rec["id"]] = rec
    return ok(ser_housing_unit(rec), 201)


@bp.get("/h2a/housing-units")
@auth(*ALL_ROLES)
def list_housing_units():
    q = request.args
    rows = list(db.housing_units.values())
    if q.get("grower_id") is not None:
        rows = [u for u in rows if u["grower_id"] == q.get("grower_id")]
    if q.get("inspection_status") is not None:
        rows = [u for u in rows
                if u["inspection_status"] == q.get("inspection_status")]
    rows = created_order(rows)
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_housing_unit(u) for u in page], total, limit, offset)


@bp.get("/h2a/housing-units/<unitId>")
@auth(*ALL_ROLES)
def get_housing_unit(unitId):
    return ok(ser_housing_unit(_unit(unitId)))


@bp.post("/h2a/housing-units/<unitId>/inspections")
@auth("HousingInspector")
def create_inspection(unitId):
    u = _unit(unitId)
    b = body()
    inspected_on = b.get("inspected_on")
    inspected = parse_date_val(inspected_on, "inspected_on")
    if inspected > clock_date():
        raise ApiError("ERR_INSPECTION_DATE_IN_FUTURE", 400,
                       "inspected_on must not be later than the clock date")
    result = b.get("result")
    if not isinstance(result, str) or result not in ("PASS", "FAIL"):
        raise invalid("result must be PASS or FAIL")
    codes = b.get("deficiency_codes", [])
    if codes is None:
        codes = []
    if not isinstance(codes, list) or \
            any(not isinstance(c, str) for c in codes):
        raise invalid("deficiency_codes must be a list of strings")
    rec = {
        "housing_unit_id": u["id"],
        "inspected_on": inspected_on,
        "result": result,
        "deficiency_codes": [] if result == "PASS" else list(codes),
    }
    stamp_immutable(rec)
    db.housing_inspections[rec["id"]] = rec
    if result == "PASS":
        u["inspection_status"] = "CERTIFIED"
        u["certified_on"] = inspected_on
    else:
        u["inspection_status"] = "FAILED"
        u["certified_on"] = None
    touch(u)
    return ok(ser_inspection(rec), 201)


@bp.get("/h2a/housing-units/<unitId>/inspections")
@auth(*ALL_ROLES)
def list_inspections(unitId):
    u = _unit(unitId)
    rows = [i for i in db.housing_inspections.values()
            if i["housing_unit_id"] == u["id"]]
    rows = created_order(rows)
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_inspection(i) for i in page], total, limit, offset)


@bp.post("/h2a/housing-units/<unitId>/expire")
@auth("ContractorAdmin")
def expire_housing_unit(unitId):
    u = _unit(unitId)
    if u["inspection_status"] != "CERTIFIED":
        raise ApiError("ERR_HOUSING_UNIT_INVALID_STATE", 409,
                       "unit is not CERTIFIED")
    valid_until = d(u["certified_on"]) + timedelta(days=365)
    if clock_date() <= valid_until:
        raise ApiError("ERR_HOUSING_CERTIFICATION_STILL_VALID", 409,
                       "certification is still valid")
    u["inspection_status"] = "EXPIRED"
    u["certified_on"] = None
    touch(u)
    return ok(ser_housing_unit(u))


# ------------------------------------------------------- housing assignments

@bp.post("/h2a/housing-assignments")
@auth("ContractorAdmin")
def create_housing_assignment():
    b = body()
    unit_id = b.get("housing_unit_id")
    worker_id = b.get("worker_id")
    assignment_id = b.get("worker_assignment_id")
    if unit_id is None:
        raise invalid("housing_unit_id is required")
    u = _unit(unit_id)
    if worker_id is None:
        raise invalid("worker_id is required")
    get_or_404(db.workers, worker_id, "ERR_WORKER_NOT_FOUND", "worker")
    if assignment_id is None:
        raise invalid("worker_assignment_id is required")
    wa = get_or_404(db.worker_assignments, assignment_id,
                    "ERR_WORKER_ASSIGNMENT_NOT_FOUND", "worker assignment")
    if wa["status"] != "ACTIVE":
        raise ApiError("ERR_ASSIGNMENT_INVALID_STATE", 409,
                       "worker assignment must be ACTIVE")
    # safety: unit currently certified
    if u["inspection_status"] != "CERTIFIED":
        raise ApiError("ERR_HOUSING_NOT_CERTIFIED", 409,
                       "housing unit is not CERTIFIED")
    valid_until = d(u["certified_on"]) + timedelta(days=365)
    if clock_date() > valid_until:
        raise ApiError("ERR_HOUSING_NOT_CERTIFIED", 409,
                       "housing unit certification validity has passed")
    # referential: unit grower == assignment's order's grower
    order = db.job_orders[wa["job_order_id"]]
    if order["grower_id"] != u["grower_id"]:
        raise ApiError("ERR_GROWER_MISMATCH", 409,
                       "housing unit grower differs from the assignment's "
                       "job order grower")
    move_in_s = b.get("move_in_date")
    move_in = parse_date_val(move_in_s, "move_in_date")
    # capacity: all OCCUPIED windows are open-ended, so any new OCCUPIED stay
    # overlaps every other OCCUPIED stay of the unit.
    overlapping = sum(
        1 for h in db.housing_assignments.values()
        if h["housing_unit_id"] == u["id"] and h["status"] == "OCCUPIED")
    if overlapping + 1 > u["capacity"]:
        raise ApiError("ERR_HOUSING_CAPACITY_EXCEEDED", 409,
                       "unit capacity would be exceeded")
    if any(h["worker_id"] == worker_id and h["status"] == "OCCUPIED"
           for h in db.housing_assignments.values()):
        raise ApiError("ERR_WORKER_HOUSING_OVERLAP", 409,
                       "worker already holds an OCCUPIED housing assignment")
    rec = {
        "housing_unit_id": u["id"],
        "worker_id": worker_id,
        "worker_assignment_id": wa["id"],
        "move_in_date": move_in_s,
        "move_out_date": None,
        "status": "OCCUPIED",
    }
    stamp_new(rec)
    db.housing_assignments[rec["id"]] = rec
    return ok(ser_housing_assignment(rec), 201)


@bp.get("/h2a/housing-assignments")
@auth(*ALL_ROLES)
def list_housing_assignments():
    q = request.args
    rows = list(db.housing_assignments.values())
    for key in ("housing_unit_id", "worker_id", "worker_assignment_id",
                "status"):
        if q.get(key) is not None:
            rows = [h for h in rows if h[key] == q.get(key)]
    rows = created_order(rows)
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_housing_assignment(h) for h in page], total, limit,
                   offset)


@bp.get("/h2a/housing-assignments/<housingAssignmentId>")
@auth(*ALL_ROLES)
def get_housing_assignment(housingAssignmentId):
    h = get_or_404(db.housing_assignments, housingAssignmentId,
                   "ERR_HOUSING_ASSIGNMENT_NOT_FOUND", "housing assignment")
    return ok(ser_housing_assignment(h))


@bp.post("/h2a/housing-assignments/<housingAssignmentId>/vacate")
@auth("ContractorAdmin")
def vacate_housing_assignment(housingAssignmentId):
    h = get_or_404(db.housing_assignments, housingAssignmentId,
                   "ERR_HOUSING_ASSIGNMENT_NOT_FOUND", "housing assignment")
    if h["status"] != "OCCUPIED":
        raise ApiError("ERR_HOUSING_ASSIGNMENT_INVALID_STATE", 409,
                       "housing assignment is not OCCUPIED")
    b = body()
    move_out_s = b.get("move_out_date")
    move_out = parse_date_val(move_out_s, "move_out_date")
    if move_out < d(h["move_in_date"]):
        raise ApiError("ERR_INVALID_DATE_RANGE", 400,
                       "move_out_date must not precede move_in_date")
    h["status"] = "VACATED"
    h["move_out_date"] = move_out_s
    touch(h)
    return ok(ser_housing_assignment(h))
