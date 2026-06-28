"""Station assignment routes (PRD 3.3; §1.5)."""
from flask import Blueprint, request

import db
import errors
import helpers
import lookups
import response
from middleware import require

bp = Blueprint("station_assignments", __name__)


@bp.post("/school/station-assignments")
@require("Instructor")
def create_assignment():
    data = helpers.body()
    helpers.require_fields(
        data, "station_id", "enrollment_id", "instructor_id", "start_iso", "end_iso",
    )
    station_id = helpers.require_str(data, "station_id")
    enrollment_id = helpers.require_str(data, "enrollment_id")
    instructor_id = helpers.require_str(data, "instructor_id")
    # Priority 4: body FK existence.
    station = lookups.fk(db.stations, station_id)
    lookups.fk(db.enrollments, enrollment_id)
    lookups.fk(db.instructors, instructor_id)
    start_dt = helpers.require_dt(data, "start_iso")
    end_dt = helpers.require_dt(data, "end_iso")

    # Priority 11: double-booking — the half-open interval [start, end) must not
    # overlap any RESERVED assignment on the SAME station. Adjacency (end==start)
    # is allowed.
    for sa in db.station_assignments.values():
        if sa["station_id"] != station_id:
            continue
        if sa["status"] != "RESERVED":
            continue
        ex_start = helpers.parse_dt(sa["start_iso"])
        ex_end = helpers.parse_dt(sa["end_iso"])
        # Half-open overlap: start < ex_end AND ex_start < end.
        if start_dt < ex_end and ex_start < end_dt:
            raise errors.station_double_booked()

    # Priority 13: station_type match + not OUT_OF_SERVICE.
    if station["status"] == "OUT_OF_SERVICE":
        raise errors.station_unavailable()

    row = {
        "station_id": station_id,
        "enrollment_id": enrollment_id,
        "instructor_id": instructor_id,
        "start_iso": db.iso(start_dt),
        "end_iso": db.iso(end_dt),
        "status": "RESERVED",
    }
    db.stamp_new(row)
    db.station_assignments[row["id"]] = row

    # Side effect: station -> OCCUPIED.
    station["status"] = "OCCUPIED"
    db.touch(station)

    return response.created(row)


@bp.get("/school/station-assignments/<sid>")
@require("Registrar", "Instructor")
def get_assignment(sid):
    row = lookups.path(db.station_assignments, sid)
    return response.ok(row)


@bp.get("/school/station-assignments")
@require("Registrar", "Instructor")
def list_assignments():
    rows = list(db.station_assignments.values())
    station_id = request.args.get("station_id")
    enrollment_id = request.args.get("enrollment_id")
    instructor_id = request.args.get("instructor_id")
    if station_id:
        rows = [r for r in rows if r["station_id"] == station_id]
    if enrollment_id:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    if instructor_id:
        rows = [r for r in rows if r["instructor_id"] == instructor_id]
    page, limit, offset, total = helpers.paginate(rows)
    return response.listing(page, limit, offset, total)


@bp.post("/school/station-assignments/<sid>/release")
@require("Instructor")
def release(sid):
    row = lookups.path(db.station_assignments, sid)
    if row["status"] != "RESERVED":
        raise errors.invalid_state()
    row["status"] = "RELEASED"
    db.touch(row)
    # Cross-entity: station OCCUPIED -> AVAILABLE.
    station = db.stations[row["station_id"]]
    station["status"] = "AVAILABLE"
    db.touch(station)
    return response.ok(row)
