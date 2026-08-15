"""Mission execution: advance gates, abort/cancel, divert, weather filing,
crew assignments (PRD §3.3-§3.5)."""

from flask import Blueprint

import calc
import services
from core import (
    ERR_AIRCRAFT_NOT_AVAILABLE, ERR_ALTERNATE_REQUIRED, ERR_AUTH_REQUIRED,
    ERR_BELOW_WEATHER_MINIMUMS, ERR_CREW_COMPOSITION_INCOMPLETE,
    ERR_CREW_UNAVAILABLE, ERR_DOC_EXPIRED, ERR_FORBIDDEN,
    ERR_GROUND_LEGS_PENDING, ERR_INVALID_STATE, ERR_REPATRIATION_NOT_READY,
    ERR_STALE_VERSION, ERR_WEATHER_ASSESSMENT_STALE, db, fail, get_body,
    list_response, must_exist, now_iso, ok_object, require_roles,
    stamp_new_immutable, stamp_new, touch, v_enum, v_int, v_num, v_str,
)
from serialize import (
    ser_crew_assignment, ser_mission, ser_weather_assessment,
)

bp = Blueprint("missions", __name__)

ALL_ROLES = ("OpsAdmin", "Dispatcher", "MedicalDirector", "FlightCrew",
             "BillingSpecialist", "QaReviewer")

MISSION_STATUSES = {
    "PLANNING", "LAUNCHED", "WEATHER_HOLD", "AT_PATIENT", "IN_TRANSIT",
    "DIVERTED", "AT_DESTINATION", "COMPLETED", "ABORTED", "CANCELLED",
}
WEATHER_DECISIONS = {"GO", "MARGINAL", "NO_GO"}
PRECIP = {"NONE", "LIGHT", "HEAVY", "ICE"}
DAY_NIGHT = {"DAY", "NIGHT"}
TERRAIN = {"FLAT", "MOUNTAINOUS"}
MISSION_ROLES = {"PILOT", "NURSE", "PARAMEDIC"}
ASSIGNMENT_STATUSES = {"ASSIGNED", "RELEASED", "COMPLETED"}

# Advance targets restricted to FlightCrew (per-transition actors, PRD §3.5)
FLIGHTCREW_ONLY_TARGETS = {"AT_PATIENT", "IN_TRANSIT", "AT_DESTINATION", "COMPLETED"}


@bp.route("/air-ambulance/missions/<rid>", methods=["GET"])
def get_mission(rid):
    require_roles(*ALL_ROLES)
    rec = must_exist(db.missions, rid, "Mission")
    return ok_object(ser_mission(rec))


@bp.route("/air-ambulance/missions", methods=["GET"])
def list_missions():
    require_roles(*ALL_ROLES)
    return list_response(
        db.missions.values(), ser_mission,
        {"mission_request_id": "mission_request_id",
         "aircraft_id": "aircraft_id", "status": "status"},
    )


# ---------------------------------------------------------------------------
# Weather block shared by launch and resume. PRD §3.4 order: decision checks
# (no assessment / NO_GO -> BELOW_WEATHER_MINIMUMS; MARGINAL without alternate
# -> ALTERNATE_REQUIRED at initial launch, BELOW_WEATHER_MINIMUMS on resume),
# then staleness (ERR_WEATHER_ASSESSMENT_STALE).
# ---------------------------------------------------------------------------


def _weather_block(mission, is_launch):
    newest = calc.newest_assessment(mission["id"])
    if newest is None:
        fail(ERR_BELOW_WEATHER_MINIMUMS, 422, "No weather assessment has been filed")
    decision = newest["decision"]
    if decision == "NO_GO":
        fail(ERR_BELOW_WEATHER_MINIMUMS, 422, "Latest weather decision is NO_GO")
    if decision == "MARGINAL":
        if is_launch:
            if not mission.get("alternate_destination"):
                fail(ERR_ALTERNATE_REQUIRED, 422,
                     "MARGINAL decision requires a filed alternate_destination")
        else:
            fail(ERR_BELOW_WEATHER_MINIMUMS, 422,
                 "Resume from hold requires a fresh GO decision")
    if not calc.assessment_fresh(newest):
        fail(ERR_WEATHER_ASSESSMENT_STALE, 422,
             "Newest weather assessment is older than 60 minutes")


def _launch_gate(mission):
    # 1. roster: every ASSIGNED assignment references an ACTIVE member
    for a in db.crew_assignments.values():
        if a["mission_id"] == mission["id"] and a["status"] == "ASSIGNED":
            member = db.crew_members.get(a["crew_member_id"])
            if member is None or member["status"] != "ACTIVE":
                fail(ERR_CREW_UNAVAILABLE, 422,
                     "Assigned crew member %s is not ACTIVE" % a["crew_member_id"])
    # 2. weather block
    _weather_block(mission, is_launch=True)
    # 3. aircraft binding: tail still bound and reading ASSIGNED
    aircraft = db.aircraft.get(mission["aircraft_id"])
    if aircraft is None or aircraft["status"] != "ASSIGNED":
        fail(ERR_AIRCRAFT_NOT_AVAILABLE, 409,
             "Mission aircraft is no longer bound/ASSIGNED")
    # 4. repatriation readiness (INTERNATIONAL_REPATRIATION only)
    if mission["transport_class"] == "INTERNATIONAL_REPATRIATION":
        case = next((c for c in db.repatriation_cases.values()
                     if c["mission_id"] == mission["id"]), None)
        if case is None or case["status"] != "READY_TO_FLY":
            fail(ERR_REPATRIATION_NOT_READY, 422,
                 "Repatriation case is not READY_TO_FLY")
        # launch-gate revalidation: stale docs lazily demote the case
        if not services.documents_valid(case):
            case["status"] = "COLLECTING"
            touch(case)
            fail(ERR_DOC_EXPIRED, 422,
                 "Repatriation documents failed launch-gate revalidation")
    # 5. fiscal gate (emergency_override bypasses ERR_AUTH_REQUIRED)
    if mission["transport_class"] in {"SCHEDULED_INTERFACILITY", "INTERNATIONAL_REPATRIATION"}:
        req = db.mission_requests.get(mission["mission_request_id"])
        override = req["emergency_override"] if req else False
        if not override:
            authorized = any(
                a["mission_id"] == mission["id"] and a["status"] in {"APPROVED", "PARTIAL"}
                for a in db.insurance_authorizations.values()
            )
            if not authorized:
                fail(ERR_AUTH_REQUIRED, 422,
                     "An APPROVED or PARTIAL insurance authorization is required")


@bp.route("/air-ambulance/missions/<rid>/advance", methods=["POST"])
def advance_mission(rid):
    user_id, role = require_roles("Dispatcher", "FlightCrew")
    mission = must_exist(db.missions, rid, "Mission")
    body = get_body()
    target = v_enum(body, "to_state", MISSION_STATUSES)
    # per-transition actor restriction (role authorization)
    if target in FLIGHTCREW_ONLY_TARGETS and role != "FlightCrew":
        fail(ERR_FORBIDDEN, 403, "Only FlightCrew may advance to %s" % target)

    current = mission["status"]
    if target == "LAUNCHED" and current == "PLANNING":
        _launch_gate(mission)
        mission["status"] = "LAUNCHED"
        mission["launched_at"] = now_iso()
        touch(mission)
    elif target == "WEATHER_HOLD" and current == "LAUNCHED":
        mission["status"] = "WEATHER_HOLD"
        touch(mission)
    elif target == "LAUNCHED" and current == "WEATHER_HOLD":
        _weather_block(mission, is_launch=False)
        mission["status"] = "LAUNCHED"
        touch(mission)
    elif target == "AT_PATIENT" and current == "LAUNCHED":
        mission["status"] = "AT_PATIENT"
        touch(mission)
    elif target == "IN_TRANSIT" and current == "AT_PATIENT":
        mission["status"] = "IN_TRANSIT"
        touch(mission)
    elif target == "AT_DESTINATION" and current in {"IN_TRANSIT", "DIVERTED"}:
        mission["status"] = "AT_DESTINATION"
        touch(mission)
    elif target == "COMPLETED" and current == "AT_DESTINATION":
        pending = any(
            l["mission_id"] == mission["id"]
            and l["status"] != "CANCELLED" and l["status"] != "COMPLETED"
            for l in db.ground_legs.values()
        )
        if pending:
            fail(ERR_GROUND_LEGS_PENDING, 409,
                 "Every non-CANCELLED ground leg must be COMPLETED first")
        mission["status"] = "COMPLETED"
        mission["completed_at"] = now_iso()
        mission["_completed_dt"] = db.clock
        services.mission_completion_cascade(mission)
        touch(mission)
    else:
        fail(ERR_INVALID_STATE, 409,
             "Mission status %s cannot advance to %s" % (current, target))
    return ok_object(ser_mission(mission))


@bp.route("/air-ambulance/missions/<rid>/abort", methods=["POST"])
def abort_mission(rid):
    require_roles("Dispatcher", "FlightCrew")
    mission = must_exist(db.missions, rid, "Mission")
    body = get_body()
    v_str(body, "reason_code")
    current = mission["status"]
    if current == "PLANNING":
        mission["status"] = "CANCELLED"
    elif current in {"LAUNCHED", "WEATHER_HOLD", "AT_PATIENT", "IN_TRANSIT"}:
        mission["status"] = "ABORTED"
    else:
        fail(ERR_INVALID_STATE, 409,
             "Mission status %s cannot be aborted/cancelled" % current)
    services.mission_teardown_cascade(mission)
    touch(mission)
    return ok_object(ser_mission(mission))


@bp.route("/air-ambulance/missions/<rid>/divert", methods=["POST"])
def divert_mission(rid):
    require_roles("FlightCrew")
    mission = must_exist(db.missions, rid, "Mission")
    body = get_body()
    new_dest = v_str(body, "new_destination_facility")
    v_str(body, "reason")
    if mission["status"] != "IN_TRANSIT":
        fail(ERR_INVALID_STATE, 409,
             "Mission status %s cannot divert" % mission["status"])
    mission["destination_facility"] = new_dest
    mission["status"] = "DIVERTED"
    services.divert_cascade(mission, new_dest)
    touch(mission)
    return ok_object(ser_mission(mission))


# ---------------------------------------------------------------------------
# Weather assessments (immutable; OCC keys on the parent mission's version)
# ---------------------------------------------------------------------------


@bp.route("/air-ambulance/weather-assessments", methods=["POST"])
def create_weather_assessment():
    require_roles("FlightCrew")
    body = get_body()
    if body.get("mission_id") is not None:
        must_exist(db.missions, body["mission_id"], "Mission")
    mission_id = v_str(body, "mission_id")
    mission = db.missions[mission_id]
    ceiling = v_int(body, "ceiling_ft", minimum=0)
    visibility = v_num(body, "visibility_sm", minimum=0)
    wind = v_int(body, "wind_kt", minimum=0)
    precip = v_enum(body, "precip", PRECIP)
    day_night = v_enum(body, "day_night", DAY_NIGHT)
    terrain = v_enum(body, "terrain", TERRAIN)
    expected = v_int(body, "expected_mission_version")
    # OCC sits at the tail of the business-rule ladder
    if expected != mission["version"]:
        fail(ERR_STALE_VERSION, 412,
             "expected_mission_version does not match the mission's current version")
    aircraft = db.aircraft.get(mission["aircraft_id"])
    decision = calc.weather_decision(
        aircraft["aircraft_class"] if aircraft else "ROTOR_WING",
        ceiling, visibility, wind, precip, day_night, terrain,
    )
    rec = stamp_new_immutable({
        "mission_id": mission_id,
        "ceiling_ft": ceiling,
        "visibility_sm": visibility,
        "wind_kt": wind,
        "precip": precip,
        "day_night": day_night,
        "terrain": terrain,
        "decision": decision,
        "assessed_at": now_iso(),
        "_assessed_dt": db.clock,
    })
    db.weather_assessments[rec["id"]] = rec
    # filing mutates the mission: last_weather_decision + version bump
    mission["last_weather_decision"] = decision
    touch(mission)
    return ok_object(ser_weather_assessment(rec), 201)


@bp.route("/air-ambulance/weather-assessments/<rid>", methods=["GET"])
def get_weather_assessment(rid):
    require_roles(*ALL_ROLES)
    rec = must_exist(db.weather_assessments, rid, "WeatherAssessment")
    return ok_object(ser_weather_assessment(rec))


@bp.route("/air-ambulance/weather-assessments", methods=["GET"])
def list_weather_assessments():
    require_roles(*ALL_ROLES)
    return list_response(
        db.weather_assessments.values(), ser_weather_assessment,
        {"mission_id": "mission_id", "decision": "decision"},
    )


# ---------------------------------------------------------------------------
# Crew assignments (post-acceptance roster adjustments)
# ---------------------------------------------------------------------------


@bp.route("/air-ambulance/crew-assignments", methods=["POST"])
def create_crew_assignment():
    require_roles("Dispatcher")
    body = get_body()
    if body.get("mission_id") is not None:
        must_exist(db.missions, body["mission_id"], "Mission")
    if body.get("crew_member_id") is not None:
        must_exist(db.crew_members, body["crew_member_id"], "CrewMember")
    mission_id = v_str(body, "mission_id")
    member_id = v_str(body, "crew_member_id")
    role_in_mission = v_enum(body, "role_in_mission", MISSION_ROLES)
    mission = db.missions[mission_id]
    if mission["status"] != "PLANNING":
        fail(ERR_INVALID_STATE, 409, "Mission is not in PLANNING")
    # PRD §3.3 stated order: member ACTIVE, then role-not-duplicated
    member = db.crew_members[member_id]
    if member["status"] != "ACTIVE":
        fail(ERR_CREW_UNAVAILABLE, 422, "Crew member %s is not ACTIVE" % member_id)
    duplicated = any(
        a["mission_id"] == mission_id and a["status"] == "ASSIGNED"
        and a["role_in_mission"] == role_in_mission
        for a in db.crew_assignments.values()
    )
    if duplicated:
        fail(ERR_CREW_COMPOSITION_INCOMPLETE, 422,
             "Role %s is already assigned on this mission" % role_in_mission)
    rec = stamp_new({
        "mission_id": mission_id,
        "crew_member_id": member_id,
        "role_in_mission": role_in_mission,
        "status": "ASSIGNED",
    })
    db.crew_assignments[rec["id"]] = rec
    return ok_object(ser_crew_assignment(rec), 201)


@bp.route("/air-ambulance/crew-assignments/<rid>", methods=["GET"])
def get_crew_assignment(rid):
    require_roles(*ALL_ROLES)
    rec = must_exist(db.crew_assignments, rid, "CrewAssignment")
    return ok_object(ser_crew_assignment(rec))


@bp.route("/air-ambulance/crew-assignments", methods=["GET"])
def list_crew_assignments():
    require_roles(*ALL_ROLES)
    return list_response(
        db.crew_assignments.values(), ser_crew_assignment,
        {"mission_id": "mission_id", "crew_member_id": "crew_member_id",
         "status": "status"},
    )
