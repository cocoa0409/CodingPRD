"""Reference data (PRD 3.1): facilities, beds, physicians, diversion events."""

from flask import Blueprint, g

from core import domain as D
from core import schema as S
from core.clock import parse_instant
from core.envelope import object_response, paginate, filter_exact
from core.errors import fail
from core.store import db, new_row, bump

bp = Blueprint("refdata", __name__)

_ERR = "ERR_INVALID_REQUEST"


# ---------------------------------------------------------------------------
# Facilities
# ---------------------------------------------------------------------------

@bp.post("/facilities")
def create_facility():
    b = S.body()
    name = S.need_str(b, "name")
    facility_code = S.need_str(b, "facility_code")
    trauma_level = S.need_enum(b, "trauma_level", D.TRAUMA_LEVELS)
    capabilities = S.need_str_list(b, "capabilities")
    # facility_code is unique across all facilities (PRD 3.1).
    for other in db.facilities.values():
        if other["facility_code"] == facility_code:
            fail(_ERR, "facility_code must be unique across all facilities.", 400)
    row = new_row("facilities", {
        "name": name,
        "facility_code": facility_code,
        "trauma_level": trauma_level,
        "capabilities": list(capabilities),
    })
    return object_response(D.serialize_facility(row), 201)


@bp.get("/facilities/<id>")
def get_facility(id):
    row = D.get_facility(id)
    if row is None:
        fail("ERR_FACILITY_NOT_FOUND", "Facility id does not exist.", 404)
    return object_response(D.serialize_facility(row), 200)


@bp.get("/facilities/<id>/beds")
def list_facility_beds(id):
    row = D.get_facility(id)
    if row is None:
        fail("ERR_FACILITY_NOT_FOUND", "Facility id does not exist.", 404)
    rows = db.ordered("beds")
    rows = [r for r in rows if r["facility_id"] == id]
    rows = filter_exact(rows, "status")
    rows = filter_exact(rows, "unit_type")
    return paginate(rows, D.serialize_bed)


@bp.get("/facilities/<id>/physicians")
def list_facility_physicians(id):
    row = D.get_facility(id)
    if row is None:
        fail("ERR_FACILITY_NOT_FOUND", "Facility id does not exist.", 404)
    rows = db.ordered("physicians")
    rows = [r for r in rows if r["facility_id"] == id]
    return paginate(rows, D.serialize_physician)


@bp.get("/facilities/<id>/diversion-events")
def list_facility_diversions(id):
    row = D.get_facility(id)
    if row is None:
        fail("ERR_FACILITY_NOT_FOUND", "Facility id does not exist.", 404)
    rows = db.ordered("diversion_events")
    rows = [r for r in rows if r["facility_id"] == id]
    return paginate(rows, D.serialize_diversion_event)


# ---------------------------------------------------------------------------
# Beds
# ---------------------------------------------------------------------------

@bp.post("/facilities/<id>/beds")
def create_bed(id):
    b = S.body()
    bed_code = S.need_str(b, "bed_code")
    unit_type = S.need_enum(b, "unit_type", D.UNIT_TYPES)
    isolation_capable = S.opt_bool(b, "isolation_capable", False)
    facility = D.get_facility(id)
    if facility is None:
        fail("ERR_FACILITY_NOT_FOUND", "Facility id does not exist.", 404)
    if g.user_id != id:
        fail("ERR_NOT_FACILITY_MANAGER",
             "BedManager X-User-ID does not equal the target facility's id.", 403)
    row = new_row("beds", {
        "facility_id": id,
        "bed_code": bed_code,
        "unit_type": unit_type,
        "isolation_capable": isolation_capable,
        "status": "AVAILABLE",
    })
    D.evaluate_saturation(id)
    return object_response(D.serialize_bed(row), 201)


# Housekeeping moves a bed among AVAILABLE / OCCUPIED / OUT_OF_SERVICE only
# (PRD 3.1); HELD is never a legal input and a HELD bed rejects the update.
_ALLOWED_PUT_TRANSITIONS = {
    ("AVAILABLE", "OCCUPIED"), ("OCCUPIED", "AVAILABLE"),
    ("AVAILABLE", "OUT_OF_SERVICE"), ("OCCUPIED", "OUT_OF_SERVICE"),
    ("OUT_OF_SERVICE", "AVAILABLE"),
    ("AVAILABLE", "AVAILABLE"), ("OCCUPIED", "OCCUPIED"),
    ("OUT_OF_SERVICE", "OUT_OF_SERVICE"),
}


@bp.put("/beds/<id>")
def update_bed(id):
    b = S.body()
    status = S.need_enum(b, "status", D.BED_STATUSES)
    bed = D.get_bed(id)
    if bed is None:
        fail("ERR_BED_NOT_FOUND", "Bed id does not exist.", 404)
    if g.user_id != bed["facility_id"]:
        fail("ERR_NOT_FACILITY_MANAGER",
             "BedManager X-User-ID does not equal the target facility's id.", 403)
    if status == "HELD" or bed["status"] == "HELD":
        fail("ERR_INVALID_STATE",
             "HELD is managed only by the bed-hold lifecycle.", 409)
    if (bed["status"], status) not in _ALLOWED_PUT_TRANSITIONS:
        fail("ERR_INVALID_STATE",
             "Bed status transition %s -> %s is not permitted."
             % (bed["status"], status), 409)
    bed["status"] = status
    bump(bed)
    D.evaluate_saturation(bed["facility_id"])
    return object_response(D.serialize_bed(bed), 200)


# ---------------------------------------------------------------------------
# Physicians
# ---------------------------------------------------------------------------

@bp.post("/physicians")
def create_physician():
    b = S.body()
    full_name = S.need_str(b, "full_name")
    facility_id = S.need_str(b, "facility_id")
    specialty = S.need_enum(b, "specialty", D.SPECIALTIES)
    is_on_call = S.opt_bool(b, "is_on_call", True)
    if D.get_facility(facility_id) is None:
        fail("ERR_FACILITY_NOT_FOUND", "Facility id does not exist.", 404)
    row = new_row("physicians", {
        "full_name": full_name,
        "facility_id": facility_id,
        "specialty": specialty,
        "is_on_call": is_on_call,
    })
    return object_response(D.serialize_physician(row), 201)


# ---------------------------------------------------------------------------
# Diversion events (PRD 2.7, 3.1)
# ---------------------------------------------------------------------------

@bp.post("/facilities/<id>/diversion-events")
def create_diversion_event(id):
    b = S.body()
    scope = S.need_enum(b, "scope", D.DIVERSION_SCOPES)
    unit_type = S.opt_enum(b, "unit_type", D.UNIT_TYPES, None)
    if scope == "SPECIFIC_UNIT":
        if unit_type is None:
            fail(_ERR, "unit_type is required when scope is SPECIFIC_UNIT.", 400)
    elif unit_type is not None:
        fail(_ERR, "unit_type is forbidden unless scope is SPECIFIC_UNIT.", 400)
    starts_raw = S.need_str(b, "starts_at")
    ends_raw = S.need_str(b, "ends_at")
    starts_at = parse_instant(starts_raw)
    ends_at = parse_instant(ends_raw)
    if starts_at is None or ends_at is None:
        fail(_ERR, "starts_at and ends_at must be ISO 8601 instants.", 400)
    if not ends_at > starts_at:
        fail(_ERR, "ends_at must be strictly later than starts_at.", 400)
    reason = S.need_str(b, "reason")
    facility = D.get_facility(id)
    if facility is None:
        fail("ERR_FACILITY_NOT_FOUND", "Facility id does not exist.", 404)
    if g.user_id != id:
        fail("ERR_NOT_FACILITY_MANAGER",
             "BedManager X-User-ID does not equal the target facility's id.", 403)
    # Closed-interval disjointness (PRD 2.7): touching endpoints count as overlap;
    # only existing SCHEDULED / ACTIVE events of the same facility block.
    for other in db.diversion_events.values():
        if other["facility_id"] != id:
            continue
        if D.diversion_effective_status(other) not in ("SCHEDULED", "ACTIVE"):
            continue
        if starts_at <= other["ends_at"] and ends_at >= other["starts_at"]:
            fail("ERR_DIVERSION_OVERLAP",
                 "The window touches or overlaps an existing diversion of this facility.",
                 409)
    row = new_row("diversion_events", {
        "facility_id": id,
        "scope": scope,
        "unit_type": unit_type,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "reason": reason,
        "auto_created": False,
        "lifted_at": None,
    })
    return object_response(D.serialize_diversion_event(row), 201)


@bp.post("/diversion-events/<id>/lift")
def lift_diversion_event(id):
    event = db.diversion_events.get(id)
    if event is None:
        fail("ERR_DIVERSION_NOT_FOUND", "DiversionEvent id does not exist.", 404)
    if g.user_id != event["facility_id"]:
        fail("ERR_NOT_FACILITY_MANAGER",
             "BedManager X-User-ID does not equal the event's facility id.", 403)
    if D.diversion_effective_status(event) not in ("SCHEDULED", "ACTIVE"):
        fail("ERR_INVALID_STATE",
             "Only a SCHEDULED or ACTIVE diversion can be lifted.", 409)
    event["lifted_at"] = db.now
    bump(event)
    return object_response(D.serialize_diversion_event(event), 200)
