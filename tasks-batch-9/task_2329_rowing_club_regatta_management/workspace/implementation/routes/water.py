"""River-condition readings, session booking and the safety-clearance chain."""
from datetime import timedelta

from flask import Blueprint

import auth
import calc
import cascade
import clock
import db
import derive
import helpers
import response
import validate
from errors import fail

bp = Blueprint("water", __name__)

LIVE_SESSION_STATUSES = ("PLANNED", "CLEARED", "LAUNCHED")
BUFFER = timedelta(minutes=calc.SHELL_TURNAROUND_BUFFER_MINUTES)


# --------------------------------------------------------------------------- #
# Readings                                                                    #
# --------------------------------------------------------------------------- #
@bp.post("/water-condition-readings")
@auth.require("SafetyOfficer")
def create_reading():
    data = validate.body()
    observed, observed_raw = validate.datetime_field(data, "observed_at")
    air = validate.number(data, "air_temp_c", one_dp=True)
    water = validate.number(data, "water_temp_c", one_dp=True)
    wind = validate.number(data, "wind_speed_kt", one_dp=True)
    visibility = validate.integer(data, "visibility_m")
    pattern = validate.enum(data, "traffic_pattern", calc.TRAFFIC_PATTERNS)

    cold, posture = derive.evaluate_posture(air, water, wind, visibility, pattern)

    reading = db.base_record(versioned=False)
    db.set_dt(reading, "observed_at", observed, observed_raw)
    reading["air_temp_c"] = air
    reading["water_temp_c"] = water
    reading["wind_speed_kt"] = wind
    reading["visibility_m"] = visibility
    reading["traffic_pattern"] = pattern
    reading["cold_water_flag"] = cold
    reading["posture"] = posture
    db.readings[reading["id"]] = reading

    if posture == "CLOSED":
        cascade.revert_cleared_sessions(observed)
    return response.created(derive.reading_out(reading))


@bp.get("/water-condition-readings/<ident>")
@auth.require("ClubAdmin", "Coach", "SafetyOfficer")
def get_reading(ident):
    reading = helpers.load("reading", ident)
    return response.ok(derive.reading_out(reading))


@bp.get("/water-condition-readings")
@auth.require("ClubAdmin", "Coach", "SafetyOfficer")
def list_readings():
    wanted = response.filters("posture")
    rows = db.ordered(db.readings, lambda r: response.matches(r, wanted))
    return response.paginate(rows, derive.reading_out)


# --------------------------------------------------------------------------- #
# Sessions                                                                    #
# --------------------------------------------------------------------------- #
@bp.post("/water-sessions")
@auth.require("Coach", "SafetyOfficer")
def book_session():
    data = validate.body()
    helpers.check_fk("shell", data, "shell_id")
    for field in ("coach_member_id", "coxswain_member_id",
                  "primary_launch_driver_member_id", "secondary_launch_driver_member_id"):
        helpers.check_fk("member", data, field)
    for value in (data.get("athlete_member_ids") or []):
        if isinstance(value, str) and value not in db.members:
            fail("ERR_MEMBER_NOT_FOUND", "No member with id %s." % value)

    shell_id = validate.string(data, "shell_id")
    kind = validate.enum(data, "session_kind", calc.SESSION_KINDS)
    start, start_raw = validate.datetime_field(data, "planned_start_at")
    end, end_raw = validate.datetime_field(data, "planned_end_at")
    coach_id = validate.string(data, "coach_member_id", required=False, nullable=True)
    cox_id = validate.string(data, "coxswain_member_id", required=False, nullable=True)
    primary_id = validate.string(data, "primary_launch_driver_member_id",
                                 required=False, nullable=True)
    secondary_id = validate.string(data, "secondary_launch_driver_member_id",
                                   required=False, nullable=True)
    athletes = validate.id_array(data, "athlete_member_ids", default=[])

    shell = db.shells[shell_id]
    helpers.not_terminal("shell", shell)

    # Rung 21: every member the booking references must be ACTIVE.
    referenced = [i for i in (coach_id, cox_id, primary_id, secondary_id) if i] + list(athletes)
    for member_id in referenced:
        helpers.member_active(db.members[member_id])

    # Rung 34: hull tier restriction over the seated crew.
    if shell["tier_restriction"] == "COMPETITIVE_ONLY":
        seated = [i for i in ([cox_id] if cox_id else []) + list(athletes)]
        for member_id in seated:
            if db.members[member_id]["tier"] != "COMPETITIVE":
                fail("ERR_TIER_NOT_PERMITTED_FOR_HULL",
                     "Hull %s seats COMPETITIVE members only." % shell["id"])

    # Rung 35: hull schedule with the 30-minute turnaround buffer.
    for other in db.sessions.values():
        if other["shell_id"] != shell_id or other["status"] not in LIVE_SESSION_STATUSES:
            continue
        other_start = db.dt(other, "planned_start_at")
        other_end = db.dt(other, "planned_end_at")
        if other_start is None or other_end is None:
            continue
        if other_start <= start:
            conflict = start < other_end + BUFFER
        else:
            conflict = other_start < end + BUFFER
        if conflict:
            fail("ERR_SHELL_WINDOW_CONFLICT",
                 "Hull %s is already booked over that window." % shell["id"])

    session = db.base_record()
    session["shell_id"] = shell_id
    session["coach_member_id"] = coach_id
    session["coxswain_member_id"] = cox_id
    session["primary_launch_driver_member_id"] = primary_id
    session["secondary_launch_driver_member_id"] = secondary_id
    session["athlete_member_ids"] = list(athletes)
    session["reading_id"] = None
    session["session_kind"] = kind
    db.set_dt(session, "planned_start_at", start, start_raw)
    db.set_dt(session, "planned_end_at", end, end_raw)
    db.set_dt(session, "actual_return_at", None)
    session["required_launch_count"] = 0
    session["assigned_launch_count"] = derive.assigned_launch_count(session)
    session["status"] = "PLANNED"
    db.sessions[session["id"]] = session
    return response.created(derive.session_out(session))


@bp.get("/water-sessions/<ident>")
@auth.require("ClubAdmin", "Coach", "SafetyOfficer", "Member")
def get_session(ident):
    session = helpers.load("session", ident)
    return response.ok(derive.session_out(session))


@bp.get("/water-sessions")
@auth.require("ClubAdmin", "Coach", "SafetyOfficer", "Member")
def list_sessions():
    wanted = response.filters("shell_id", "coach_member_id", "coxswain_member_id",
                              "primary_launch_driver_member_id",
                              "secondary_launch_driver_member_id",
                              "athlete_member_ids", "reading_id", "status")
    rows = db.ordered(db.sessions, lambda s: response.matches(s, wanted))
    return response.paginate(rows, derive.session_out)


@bp.post("/water-sessions/<ident>/clear")
@auth.require("SafetyOfficer")
def clear_session(ident):
    session = helpers.load("session", ident)
    data = validate.body()
    helpers.check_fk("reading", data, "reading_id")
    reading_id = validate.string(data, "reading_id")

    helpers.not_terminal("session", session)

    shell = db.shells.get(session["shell_id"])
    if shell is None or shell["status"] != "AVAILABLE":
        fail("ERR_SHELL_NOT_AVAILABLE",
             "Hull %s is not AVAILABLE." % session["shell_id"])

    # Rung 21.
    for member_id in derive.session_member_ids(session):
        member = db.members.get(member_id)
        if member is not None:
            helpers.member_active(member)

    # Rung 24: the coach running the outing may not sign its own clearance.
    if session["coach_member_id"] and auth.actor_id() == session["coach_member_id"]:
        fail("ERR_SELF_CLEARANCE_FORBIDDEN",
             "The session's own coach may not sign its safety clearance.")

    reading = db.readings[reading_id]
    if reading["posture"] not in ("OPEN", "RESTRICTED"):
        fail("ERR_WATER_CLOSED", "The river posture is CLOSED.")

    # Rung 28: swim tests for the seated crew.
    swim_ids = list(session["athlete_member_ids"] or [])
    if session["coxswain_member_id"]:
        swim_ids.append(session["coxswain_member_id"])
    for member_id in swim_ids:
        member = db.members.get(member_id)
        if member is None or not derive.swim_test_valid(member):
            fail("ERR_SWIM_TEST_MISSING",
                 "Member %s has no current swim test." % member_id)

    # Rung 29: coxswain certification.
    if session["coxswain_member_id"]:
        cox = db.members.get(session["coxswain_member_id"])
        if cox is None or not derive.coxswain_cert_valid(cox):
            fail("ERR_COXSWAIN_CERT_EXPIRED",
                 "The coxswain's certification is missing or expired.")

    # Rung 30: coach certification.
    if session["coach_member_id"]:
        coach = db.members.get(session["coach_member_id"])
        if coach is None or not derive.coach_cert_valid(coach):
            fail("ERR_COACH_CERT_EXPIRED",
                 "The coach's certification is missing or expired.")

    # Rung 31: launch-driver certification and club role.
    drivers = [session[f] for f in ("primary_launch_driver_member_id",
                                    "secondary_launch_driver_member_id") if session[f]]
    for member_id in drivers:
        driver = db.members.get(member_id)
        if driver is None or not derive.launch_cert_valid(driver):
            fail("ERR_LAUNCH_CERT_EXPIRED",
                 "Launch driver %s is not currently certified." % member_id)

    # Rung 32: launch coverage.
    required = derive.required_launch_count(session, reading)
    assigned = derive.assigned_launch_count(session)
    if assigned < required:
        fail("ERR_LAUNCH_COVERAGE_INSUFFICIENT",
             "This outing needs %d safety launches but has %d." % (required, assigned))

    # Rung 36: launch drivers spread too thin (strict intersection, no buffer).
    start = db.dt(session, "planned_start_at")
    end = db.dt(session, "planned_end_at")
    for member_id in drivers:
        driver = db.members[member_id]
        overlaps = 0
        for other in db.sessions.values():
            if other["id"] == session["id"] or other["status"] not in ("CLEARED", "LAUNCHED"):
                continue
            if member_id not in (other["primary_launch_driver_member_id"],
                                 other["secondary_launch_driver_member_id"]):
                continue
            other_start = db.dt(other, "planned_start_at")
            other_end = db.dt(other, "planned_end_at")
            if other_start is None or other_end is None:
                continue
            if start < other_end and other_start < end:
                overlaps += 1
        if overlaps >= driver["launch_supervision_limit"]:
            fail("ERR_LAUNCH_DRIVER_OVERBOOKED",
                 "Launch driver %s is already covering %d overlapping outings."
                 % (member_id, overlaps))

    if session["status"] != "PLANNED":
        helpers.invalid_transition(
            "Only a PLANNED session may be cleared; this one is %s." % session["status"])

    session["reading_id"] = reading_id
    session["required_launch_count"] = required
    session["assigned_launch_count"] = assigned
    session["status"] = "CLEARED"
    db.touch(session)
    shell["status"] = "ASSIGNED"
    db.touch(shell)
    return response.ok(derive.session_out(session))


@bp.post("/water-sessions/<ident>/launch")
@auth.require("SafetyOfficer")
def launch_session(ident):
    session = helpers.load("session", ident)
    data = validate.body()
    validate.string(data, "note", required=False, nullable=True)

    helpers.not_terminal("session", session)
    if session["status"] != "CLEARED":
        fail("ERR_SESSION_NOT_CLEARED",
             "Session %s is %s, not CLEARED." % (session["id"], session["status"]))

    now = clock.now()
    start = db.dt(session, "planned_start_at")
    end = db.dt(session, "planned_end_at")
    if start is not None and now < start:
        helpers.invalid_transition("The water window has not opened yet.")
    if end is not None and now >= end:
        helpers.invalid_transition("The water window has already closed.")

    session["status"] = "LAUNCHED"
    db.touch(session)
    return response.ok(derive.session_out(session))


@bp.post("/water-sessions/<ident>/return")
@auth.require("SafetyOfficer")
def return_session(ident):
    session = helpers.load("session", ident)
    data = validate.body()
    validate.string(data, "note", required=False, nullable=True)

    helpers.not_terminal("session", session)
    if session["status"] != "LAUNCHED":
        fail("ERR_SESSION_NOT_LAUNCHED",
             "Session %s is %s, not LAUNCHED." % (session["id"], session["status"]))

    session["status"] = "RETURNED"
    db.set_dt(session, "actual_return_at", clock.now())
    db.touch(session)
    cascade.release_shell(db.shells.get(session["shell_id"]), ignore_session_id=session["id"])
    for member_id in (session["athlete_member_ids"] or []):
        db.touch(db.members.get(member_id))
    return response.ok(derive.session_out(session))


@bp.post("/water-sessions/<ident>/cancel")
@auth.require("Coach", "SafetyOfficer")
def cancel_session_route(ident):
    session = helpers.load("session", ident)
    data = validate.body()
    validate.string(data, "reason")

    helpers.not_terminal("session", session)
    if session["status"] not in ("PLANNED", "CLEARED"):
        helpers.invalid_transition(
            "Only a PLANNED or CLEARED session may be cancelled; this one is %s."
            % session["status"])

    cascade.cancel_session(session)
    return response.ok(derive.session_out(session))
