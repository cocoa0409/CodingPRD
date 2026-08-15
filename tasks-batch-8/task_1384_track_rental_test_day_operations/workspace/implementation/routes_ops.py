"""Sessions, incidents, noise readings, garage & paddock assignments."""

import uuid

from flask import Blueprint

import db
import errors
import helpers as h
import response

bp = Blueprint("ops", __name__)

ALL_ROLES = ("TrackOps", "SafetyOfficer", "Coach", "Organizer")


def _touch(resource):
    resource["updated_at"] = h.now_str()
    resource["version"] += 1


def _resolve_session_on_day(day, session_id):
    session = db.sessions.get(session_id)
    if session is None or session["track_day_id"] != day["id"]:
        raise errors.not_found("session %s not found on this track day" % session_id)
    return session


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------
@bp.route("/tracks/<tid>/track-days/<tdid>/sessions", methods=["POST"])
def create_session(tid, tdid):
    h.require_roles("TrackOps")
    track, day = h.resolve_track_day(tid, tdid)
    data = h.body()
    rental_block_id = h.req_string(data, "rental_block_id")
    run_group_class = h.req_enum(data, "run_group_class", h.RUN_GROUP_CLASSES)
    block = db.rental_blocks.get(rental_block_id)
    if block is None or block["track_day_id"] != day["id"]:
        raise errors.not_found("rental block %s not found on this track day" % rental_block_id)
    # Liveness (priority 6)
    if day["status"] in ("CANCELLED", "CLOSED"):
        raise errors.track_day_not_live()
    # Posture (priority 8)
    if day["posture"] == "SUSPENDED":
        raise errors.track_suspended()
    session = {
        "id": str(uuid.uuid4()),
        "track_day_id": day["id"],
        "rental_block_id": block["id"],
        "run_group_class": run_group_class,
        "status": "GREEN",
        "started_at_utc": h.now_str(),
        "ended_at_utc": None,
        "lap_count": 0,
        "max_db_observed": 0,
        "created_at": h.now_str(),
        "updated_at": h.now_str(),
        "version": 1,
    }
    db.sessions[session["id"]] = session
    # First session to GREEN flips the day OPEN -> RUNNING; version advances with that cascade.
    if day["status"] == "OPEN":
        day["status"] = "RUNNING"
        _touch(day)
    return response.success(h.serialize_session(session), 201)


@bp.route("/tracks/<tid>/track-days/<tdid>/sessions/<sid>", methods=["GET"])
def get_session(tid, tdid, sid):
    h.require_roles(*ALL_ROLES)
    _, _, session = h.resolve_session(tid, tdid, sid)
    return response.success(h.serialize_session(session), 200)


@bp.route("/tracks/<tid>/track-days/<tdid>/sessions", methods=["GET"])
def list_sessions(tid, tdid):
    h.require_roles(*ALL_ROLES)
    _, day = h.resolve_track_day(tid, tdid)
    status = h.query_enum("status", h.SESSION_STATUSES)
    rental_block_id = h.query_string("rental_block_id")
    limit, offset = h.pagination()
    items = [s for s in db.sessions.values() if s["track_day_id"] == day["id"]]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if rental_block_id is not None:
        items = [s for s in items if s["rental_block_id"] == rental_block_id]
    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([h.serialize_session(s) for s in page], total, limit, offset)


@bp.route("/tracks/<tid>/track-days/<tdid>/sessions/<sid>/checkered", methods=["POST"])
def checkered_session(tid, tdid, sid):
    h.require_roles("TrackOps")
    _, _, session = h.resolve_session(tid, tdid, sid)
    h.body()
    if session["status"] != "GREEN" or session["lap_count"] < h.MIN_LAPS_FOR_CHECKERED:
        raise errors.invalid_state("checkered requires a GREEN session with at least the minimum lap count")
    session["status"] = "CHECKERED"
    session["ended_at_utc"] = h.now_str()
    _touch(session)
    return response.success(h.serialize_session(session), 200)


@bp.route("/tracks/<tid>/track-days/<tdid>/sessions/<sid>/lap_event", methods=["POST"])
def lap_event(tid, tdid, sid):
    h.require_roles("TrackOps")
    _, _, session = h.resolve_session(tid, tdid, sid)
    data = h.body()
    driver_id = h.opt_string(data, "driver_id")
    if driver_id is not None:
        driver = db.drivers.get(driver_id)
        if driver is None:
            raise errors.not_found("driver %s not found" % driver_id)
        if not driver["cleared_to_run"]:
            raise errors.driver_not_cleared()
    session["lap_count"] += 1
    _touch(session)
    return response.success(h.serialize_session(session), 200)


# ---------------------------------------------------------------------------
# Incident
# ---------------------------------------------------------------------------
@bp.route("/tracks/<tid>/track-days/<tdid>/incidents", methods=["POST"])
def create_incident(tid, tdid):
    role = h.require_roles("TrackOps", "SafetyOfficer")
    track, day = h.resolve_track_day(tid, tdid)
    data = h.body()
    session_id = h.req_string(data, "session_id")
    severity = h.req_enum(data, "severity", h.SEVERITIES)
    reported_by_user_id = h.req_string(data, "reported_by_user_id")
    session = _resolve_session_on_day(day, session_id)
    # Liveness (priority 6)
    if day["status"] in ("CANCELLED", "CLOSED"):
        raise errors.track_day_not_live()
    incident = {
        "id": str(uuid.uuid4()),
        "track_day_id": day["id"],
        "session_id": session["id"],
        "severity": severity,
        "status": "OPEN",
        "reported_by_user_id": reported_by_user_id,
        "cleared_by_user_id": None,
        "created_at": h.now_str(),
        "updated_at": h.now_str(),
        "version": 1,
    }
    db.incidents[incident["id"]] = incident
    day["open_incident_count"] += 1
    if severity in ("MEDIUM", "HIGH", "CRITICAL") and session["status"] == "GREEN":
        session["status"] = "RED"
        _touch(session)
    if severity in ("HIGH", "CRITICAL") and day["status"] == "RUNNING":
        day["status"] = "STOPPED"
        for s in db.sessions.values():
            if s["track_day_id"] == day["id"] and s["status"] == "GREEN":
                s["status"] = "RED"
                _touch(s)
    h.recompute_posture(day)
    _touch(day)
    return response.success(h.serialize_incident(incident), 201)


@bp.route("/tracks/<tid>/track-days/<tdid>/incidents/<iid>", methods=["GET"])
def get_incident(tid, tdid, iid):
    h.require_roles("TrackOps", "SafetyOfficer")
    _, _, incident = h.resolve_incident(tid, tdid, iid)
    return response.success(h.serialize_incident(incident), 200)


@bp.route("/tracks/<tid>/track-days/<tdid>/incidents", methods=["GET"])
def list_incidents(tid, tdid):
    h.require_roles("TrackOps", "SafetyOfficer")
    _, day = h.resolve_track_day(tid, tdid)
    status = h.query_enum("status", h.INCIDENT_STATUSES)
    severity = h.query_enum("severity", h.SEVERITIES)
    limit, offset = h.pagination()
    items = [i for i in db.incidents.values() if i["track_day_id"] == day["id"]]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    if severity is not None:
        items = [i for i in items if i["severity"] == severity]
    items.sort(key=lambda i: i["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([h.serialize_incident(i) for i in page], total, limit, offset)


@bp.route("/tracks/<tid>/track-days/<tdid>/incidents/<iid>/investigate", methods=["POST"])
def investigate_incident(tid, tdid, iid):
    h.require_roles("SafetyOfficer")
    _, _, incident = h.resolve_incident(tid, tdid, iid)
    h.body()
    if incident["status"] != "OPEN":
        raise errors.invalid_state("incident must be OPEN to investigate")
    incident["status"] = "INVESTIGATING"
    _touch(incident)
    return response.success(h.serialize_incident(incident), 200)


@bp.route("/tracks/<tid>/track-days/<tdid>/incidents/<iid>/clear", methods=["POST"])
def clear_incident(tid, tdid, iid):
    h.require_roles("SafetyOfficer")
    _, day, incident = h.resolve_incident(tid, tdid, iid)
    data = h.body()
    cleared_by_user_id = h.req_string(data, "cleared_by_user_id")
    # State check (priority 7) fires before segregation of duties (priority 9).
    if incident["status"] == "INVESTIGATING":
        pass
    elif incident["status"] == "OPEN" and incident["severity"] == "LOW":
        pass
    else:
        raise errors.invalid_state("incident cannot be cleared from its current state")
    if cleared_by_user_id == incident["reported_by_user_id"]:
        raise errors.segregation_of_duties("cleared_by_user_id must differ from reported_by_user_id")
    incident["status"] = "CLEARED"
    incident["cleared_by_user_id"] = cleared_by_user_id
    _touch(incident)
    day["open_incident_count"] -= 1
    h.recompute_posture(day)
    _touch(day)
    return response.success(h.serialize_incident(incident), 200)


# ---------------------------------------------------------------------------
# NoiseReading
# ---------------------------------------------------------------------------
@bp.route("/tracks/<tid>/track-days/<tdid>/noise-readings", methods=["POST"])
def create_noise_reading(tid, tdid):
    h.require_roles("TrackOps", "SafetyOfficer")
    track, day = h.resolve_track_day(tid, tdid)
    data = h.body()
    session_id = h.req_string(data, "session_id")
    db_level = h.req_int(data, "db_level")
    if "recorded_at_utc" not in data:
        raise errors.invalid_request("field 'recorded_at_utc' is required")
    recorded_dt = h.parse_dt(data["recorded_at_utc"])
    session = _resolve_session_on_day(day, session_id)
    reading = {
        "id": str(uuid.uuid4()),
        "track_day_id": day["id"],
        "session_id": session["id"],
        "db_level": db_level,
        "recorded_at_utc": h.fmt_dt(recorded_dt),
        "breach": db_level > track["noise_limit_db"],
        "created_at": h.now_str(),
    }
    db.noise_readings[reading["id"]] = reading
    if db_level > session["max_db_observed"]:
        session["max_db_observed"] = db_level
    h.recompute_noise_breach_count(day)
    h.recompute_posture(day)
    return response.success(h.serialize_noise_reading(reading), 201)


@bp.route("/tracks/<tid>/track-days/<tdid>/noise-readings", methods=["GET"])
def list_noise_readings(tid, tdid):
    h.require_roles(*ALL_ROLES)
    _, day = h.resolve_track_day(tid, tdid)
    session_id = h.query_string("session_id")
    breach = h.parse_bool_param("breach")
    limit, offset = h.pagination()
    items = [n for n in db.noise_readings.values() if n["track_day_id"] == day["id"]]
    if session_id is not None:
        items = [n for n in items if n["session_id"] == session_id]
    if breach is not None:
        items = [n for n in items if n["breach"] == breach]
    items.sort(key=lambda n: n["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([h.serialize_noise_reading(n) for n in page], total, limit, offset)


# ---------------------------------------------------------------------------
# GarageAssignment
# ---------------------------------------------------------------------------
@bp.route("/tracks/<tid>/track-days/<tdid>/garage-assignments", methods=["POST"])
def create_garage_assignment(tid, tdid):
    h.require_roles("TrackOps")
    track, day = h.resolve_track_day(tid, tdid)
    data = h.body()
    booking_id = h.req_string(data, "booking_id")
    bay_number = h.req_int(data, "bay_number")
    power_hookups = h.req_int(data, "power_hookups")
    water_hookup = h.req_bool(data, "water_hookup")
    expected = h.req_int(data, "expected_track_day_version")
    if bay_number < 1 or bay_number > track["garage_bay_count"]:
        raise errors.invalid_request("bay_number must run from 1 up to the track's garage_bay_count")
    if power_hookups < 0:
        raise errors.invalid_request("power_hookups must be zero or more")
    booking = db.bookings.get(booking_id)
    if booking is None:
        raise errors.not_found("booking %s not found" % booking_id)
    block = db.rental_blocks.get(booking["rental_block_id"])
    if block is None or block["track_day_id"] != day["id"]:
        raise errors.not_found("booking %s not found on this track day" % booking_id)
    # OCC (priority 5)
    if expected != day["version"]:
        raise errors.stale_version("expected_track_day_version does not match the track day's current version")
    # Liveness (priority 6)
    if day["status"] in ("CANCELLED", "CLOSED"):
        raise errors.track_day_not_live()
    # Posture (priority 8)
    if day["posture"] == "SUSPENDED":
        raise errors.track_suspended()
    # Occupancy (priority 14)
    for other in db.garage_assignments.values():
        if (other["track_day_id"] == day["id"]
                and other["bay_number"] == bay_number
                and other["status"] == "ACTIVE"):
            raise errors.bay_occupied()
    assignment = {
        "id": str(uuid.uuid4()),
        "track_day_id": day["id"],
        "booking_id": booking["id"],
        "bay_number": bay_number,
        "power_hookups": power_hookups,
        "water_hookup": water_hookup,
        "garage_utility_fee_cents": h.garage_utility_fee_cents(power_hookups, water_hookup),
        "status": "ACTIVE",
        "created_at": h.now_str(),
        "updated_at": h.now_str(),
        "version": 1,
    }
    db.garage_assignments[assignment["id"]] = assignment
    _touch(day)
    return response.success(h.serialize_garage_assignment(assignment), 201)


@bp.route("/tracks/<tid>/track-days/<tdid>/garage-assignments/<gid>", methods=["GET"])
def get_garage_assignment(tid, tdid, gid):
    h.require_roles(*ALL_ROLES)
    _, _, assignment = h.resolve_garage_assignment(tid, tdid, gid)
    return response.success(h.serialize_garage_assignment(assignment), 200)


@bp.route("/tracks/<tid>/track-days/<tdid>/garage-assignments", methods=["GET"])
def list_garage_assignments(tid, tdid):
    h.require_roles(*ALL_ROLES)
    _, day = h.resolve_track_day(tid, tdid)
    status = h.query_enum("status", h.ASSIGNMENT_STATUSES)
    booking_id = h.query_string("booking_id")
    limit, offset = h.pagination()
    items = [g for g in db.garage_assignments.values() if g["track_day_id"] == day["id"]]
    if status is not None:
        items = [g for g in items if g["status"] == status]
    if booking_id is not None:
        items = [g for g in items if g["booking_id"] == booking_id]
    items.sort(key=lambda g: g["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([h.serialize_garage_assignment(g) for g in page], total, limit, offset)


@bp.route("/tracks/<tid>/track-days/<tdid>/garage-assignments/<gid>/release", methods=["POST"])
def release_garage_assignment(tid, tdid, gid):
    h.require_roles("TrackOps")
    _, _, assignment = h.resolve_garage_assignment(tid, tdid, gid)
    h.body()
    if assignment["status"] != "ACTIVE":
        raise errors.invalid_state("garage assignment must be ACTIVE to release")
    assignment["status"] = "RELEASED"
    _touch(assignment)
    return response.success(h.serialize_garage_assignment(assignment), 200)


# ---------------------------------------------------------------------------
# PaddockAssignment
# ---------------------------------------------------------------------------
@bp.route("/tracks/<tid>/track-days/<tdid>/paddock-assignments", methods=["POST"])
def create_paddock_assignment(tid, tdid):
    h.require_roles("TrackOps")
    track, day = h.resolve_track_day(tid, tdid)
    data = h.body()
    booking_id = h.req_string(data, "booking_id")
    stall_number = h.req_int(data, "stall_number")
    if stall_number < 1 or stall_number > track["paddock_stall_count"]:
        raise errors.invalid_request("stall_number must run from 1 up to the track's paddock_stall_count")
    booking = db.bookings.get(booking_id)
    if booking is None:
        raise errors.not_found("booking %s not found" % booking_id)
    block = db.rental_blocks.get(booking["rental_block_id"])
    if block is None or block["track_day_id"] != day["id"]:
        raise errors.not_found("booking %s not found on this track day" % booking_id)
    # Liveness (priority 6)
    if day["status"] in ("CANCELLED", "CLOSED"):
        raise errors.track_day_not_live()
    # Occupancy (priority 15)
    for other in db.paddock_assignments.values():
        if (other["track_day_id"] == day["id"]
                and other["stall_number"] == stall_number
                and other["status"] == "ACTIVE"):
            raise errors.stall_occupied()
    assignment = {
        "id": str(uuid.uuid4()),
        "track_day_id": day["id"],
        "booking_id": booking["id"],
        "stall_number": stall_number,
        "status": "ACTIVE",
        "created_at": h.now_str(),
        "updated_at": h.now_str(),
        "version": 1,
    }
    db.paddock_assignments[assignment["id"]] = assignment
    return response.success(h.serialize_paddock_assignment(assignment), 201)


@bp.route("/tracks/<tid>/track-days/<tdid>/paddock-assignments/<pid>", methods=["GET"])
def get_paddock_assignment(tid, tdid, pid):
    h.require_roles(*ALL_ROLES)
    _, _, assignment = h.resolve_paddock_assignment(tid, tdid, pid)
    return response.success(h.serialize_paddock_assignment(assignment), 200)


@bp.route("/tracks/<tid>/track-days/<tdid>/paddock-assignments", methods=["GET"])
def list_paddock_assignments(tid, tdid):
    h.require_roles(*ALL_ROLES)
    _, day = h.resolve_track_day(tid, tdid)
    status = h.query_enum("status", h.ASSIGNMENT_STATUSES)
    booking_id = h.query_string("booking_id")
    limit, offset = h.pagination()
    items = [p for p in db.paddock_assignments.values() if p["track_day_id"] == day["id"]]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if booking_id is not None:
        items = [p for p in items if p["booking_id"] == booking_id]
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([h.serialize_paddock_assignment(p) for p in page], total, limit, offset)


@bp.route("/tracks/<tid>/track-days/<tdid>/paddock-assignments/<pid>/release", methods=["POST"])
def release_paddock_assignment(tid, tdid, pid):
    h.require_roles("TrackOps")
    _, _, assignment = h.resolve_paddock_assignment(tid, tdid, pid)
    h.body()
    if assignment["status"] != "ACTIVE":
        raise errors.invalid_state("paddock assignment must be ACTIVE to release")
    assignment["status"] = "RELEASED"
    _touch(assignment)
    return response.success(h.serialize_paddock_assignment(assignment), 200)
