"""Mission request intake, clinical triage, and acceptance (PRD §3.2-§3.3)."""

from datetime import timedelta

from flask import Blueprint

import calc
from core import (
    ERR_ACUITY_EXCEEDS_CONFIG, ERR_AIRCRAFT_NOT_AVAILABLE,
    ERR_AIRCRAFT_SCHEDULE_CONFLICT, ERR_CREW_COMPOSITION_INCOMPLETE,
    ERR_CREW_UNAVAILABLE, ERR_INVALID_STATE, ERR_REQUEST_NOT_TRIAGED,
    ERR_VALIDATION, db, fail, get_body, list_response, must_exist, now_dt,
    ok_object, require_roles, stamp_new, touch, v_bool, v_dt, v_enum, v_int,
    v_num, v_str,
)
from serialize import ser_mission, ser_mission_request

bp = Blueprint("requests", __name__)

ALL_ROLES = ("OpsAdmin", "Dispatcher", "MedicalDirector", "FlightCrew",
             "BillingSpecialist", "QaReviewer")

TRANSPORT_CLASSES = {
    "EMERGENCY_SCENE", "EMERGENCY_INTERFACILITY",
    "SCHEDULED_INTERFACILITY", "INTERNATIONAL_REPATRIATION",
}
MISSION_ROLES = {"PILOT", "NURSE", "PARAMEDIC"}
REQUEST_STATUSES = {"RECEIVED", "TRIAGED", "PENDING_INFO", "ACCEPTED", "DECLINED"}


def _subscale(body, field):
    return v_int(body, field, minimum=0, maximum=10)


@bp.route("/air-ambulance/mission-requests", methods=["POST"])
def create_mission_request():
    require_roles("Dispatcher")
    body = get_body()
    if "patient_id" in body and body["patient_id"] is not None:
        must_exist(db.patients, body["patient_id"], "Patient")
    transport_class = v_enum(body, "transport_class", TRANSPORT_CLASSES)
    patient_id = v_str(body, "patient_id")
    origin = v_str(body, "origin_facility")
    dest = v_str(body, "destination_facility")
    dest_country = body.get("destination_country")
    if transport_class == "INTERNATIONAL_REPATRIATION":
        # destination_country is required exactly for repatriation requests
        dest_country = v_str(body, "destination_country")
    elif dest_country is not None and not isinstance(dest_country, str):
        fail(ERR_VALIDATION, 400, "destination_country must be a string")
    cardio = _subscale(body, "reported_cardio")
    resp = _subscale(body, "reported_resp")
    neuro = _subscale(body, "reported_neuro")
    interv = _subscale(body, "reported_interventions")
    onset_raw, onset = v_dt(body, "onset_iso")
    emergency_override = v_bool(body, "emergency_override", default=False)
    score = calc.triage_score(cardio, resp, neuro, interv)
    rec = stamp_new({
        "patient_id": patient_id,
        "transport_class": transport_class,
        "origin_facility": origin,
        "destination_facility": dest,
        "destination_country": dest_country,
        "reported_cardio": cardio,
        "reported_resp": resp,
        "reported_neuro": neuro,
        "reported_interventions": interv,
        "onset_iso": onset_raw,
        "triage_acuity_score": calc.score_json(score),
        "acceptance_acuity_score": None,
        "acuity_tier": None,
        "emergency_override": emergency_override,
        "status": "RECEIVED",
        "_onset": onset,
    })
    db.mission_requests[rec["id"]] = rec
    return ok_object(ser_mission_request(rec), 201)


@bp.route("/air-ambulance/mission-requests/<rid>", methods=["GET"])
def get_mission_request(rid):
    require_roles(*ALL_ROLES)
    rec = must_exist(db.mission_requests, rid, "MissionRequest")
    return ok_object(ser_mission_request(rec))


@bp.route("/air-ambulance/mission-requests", methods=["GET"])
def list_mission_requests():
    require_roles(*ALL_ROLES)
    return list_response(
        db.mission_requests.values(), ser_mission_request,
        {"patient_id": "patient_id", "status": "status"},
    )


def _score_acceptance(req, cardio, resp, neuro, interv):
    score = calc.acceptance_score(cardio, resp, neuro, interv, req["_onset"], now_dt())
    req["acceptance_acuity_score"] = calc.score_json(score)
    req["acuity_tier"] = calc.tier_of(score)


@bp.route("/air-ambulance/mission-requests/<rid>/triage", methods=["POST"])
def triage_request(rid):
    require_roles("MedicalDirector")
    req = must_exist(db.mission_requests, rid, "MissionRequest")
    body = get_body()
    cardio = _subscale(body, "verified_cardio")
    resp = _subscale(body, "verified_resp")
    neuro = _subscale(body, "verified_neuro")
    interv = _subscale(body, "verified_interventions")
    override = v_bool(body, "emergency_override", default=None)
    if req["status"] != "RECEIVED":
        fail(ERR_INVALID_STATE, 409,
             "MissionRequest status %s cannot be triaged" % req["status"])
    _score_acceptance(req, cardio, resp, neuro, interv)
    if override is not None:
        req["emergency_override"] = override
    req["status"] = "TRIAGED"
    touch(req)
    return ok_object(ser_mission_request(req))


@bp.route("/air-ambulance/mission-requests/<rid>/request-info", methods=["POST"])
def request_info(rid):
    require_roles("MedicalDirector")
    req = must_exist(db.mission_requests, rid, "MissionRequest")
    body = get_body()
    v_str(body, "info_note")
    if req["status"] != "TRIAGED":
        fail(ERR_INVALID_STATE, 409,
             "MissionRequest status %s cannot be sent back for info" % req["status"])
    req["status"] = "PENDING_INFO"
    touch(req)
    return ok_object(ser_mission_request(req))


@bp.route("/air-ambulance/mission-requests/<rid>/provide-info", methods=["POST"])
def provide_info(rid):
    require_roles("Dispatcher")
    req = must_exist(db.mission_requests, rid, "MissionRequest")
    body = get_body()
    cardio = _subscale(body, "updated_cardio")
    resp = _subscale(body, "updated_resp")
    neuro = _subscale(body, "updated_neuro")
    interv = _subscale(body, "updated_interventions")
    v_str(body, "info_note")
    if req["status"] != "PENDING_INFO":
        fail(ERR_INVALID_STATE, 409,
             "MissionRequest status %s cannot receive info" % req["status"])
    _score_acceptance(req, cardio, resp, neuro, interv)
    req["status"] = "TRIAGED"
    touch(req)
    return ok_object(ser_mission_request(req))


@bp.route("/air-ambulance/mission-requests/<rid>/decline", methods=["POST"])
def decline_request(rid):
    require_roles("MedicalDirector")
    req = must_exist(db.mission_requests, rid, "MissionRequest")
    body = get_body()
    v_str(body, "reason")
    if req["status"] not in {"TRIAGED", "PENDING_INFO"}:
        fail(ERR_INVALID_STATE, 409,
             "MissionRequest status %s cannot be declined" % req["status"])
    req["status"] = "DECLINED"
    touch(req)
    return ok_object(ser_mission_request(req))


# ---------------------------------------------------------------------------
# Acceptance (PRD §3.3): fixed check order, early failure masks later ones.
# ---------------------------------------------------------------------------


def _window_overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap; endpoint-touching adjacency allowed."""
    return a_start < b_end and b_start < a_end


@bp.route("/air-ambulance/mission-requests/<rid>/accept", methods=["POST"])
def accept_request(rid):
    require_roles("Dispatcher")
    req = must_exist(db.mission_requests, rid, "MissionRequest")
    body = get_body()

    # --- existence (priority 3): body FKs left-to-right --------------------
    if body.get("aircraft_id") is not None:
        must_exist(db.aircraft, body["aircraft_id"], "Aircraft")
    crew_entries = body.get("crew")
    if isinstance(crew_entries, list):
        for entry in crew_entries:
            if isinstance(entry, dict) and entry.get("crew_member_id") is not None:
                must_exist(db.crew_members, entry["crew_member_id"], "CrewMember")

    # --- shape (priority 4) -------------------------------------------------
    aircraft_id = v_str(body, "aircraft_id")
    if not isinstance(crew_entries, list) or not crew_entries:
        fail(ERR_VALIDATION, 400, "Field 'crew' must be a non-empty array")
    cleaned_crew = []
    for entry in crew_entries:
        if not isinstance(entry, dict):
            fail(ERR_VALIDATION, 400, "Each crew entry must be an object")
        cleaned_crew.append({
            "crew_member_id": v_str(entry, "crew_member_id"),
            "role_in_mission": v_enum(entry, "role_in_mission", MISSION_ROLES),
        })
    est_miles = v_num(body, "estimated_loaded_miles", minimum=0, exclusive_min=True)
    launch_raw, launch = v_dt(body, "planned_launch_iso")
    duration = v_int(body, "planned_duration_min", minimum=1)
    alternate = body.get("alternate_destination")
    if alternate is not None and not isinstance(alternate, str):
        fail(ERR_VALIDATION, 400, "alternate_destination must be a string")

    # --- state (priority 6) -------------------------------------------------
    if req["status"] != "TRIAGED":
        fail(ERR_REQUEST_NOT_TRIAGED, 409,
             "MissionRequest status %s cannot be accepted" % req["status"])

    aircraft = db.aircraft[aircraft_id]

    # --- business, in the workflow's stated order ---------------------------
    # 1. aircraft capability rank must meet the acuity tier
    if calc.CONFIG_RANK[aircraft["medical_config"]] < calc.TIER_RANK[req["acuity_tier"]]:
        fail(ERR_ACUITY_EXCEEDS_CONFIG, 422,
             "Aircraft medical_config is below the request acuity tier")
    # 2. roster covers the tier minimum, no duplicated role
    required = {"PILOT", "NURSE"}
    if req["acuity_tier"] == "CCT":
        required.add("PARAMEDIC")
    role_counts = {}
    for entry in cleaned_crew:
        role_counts[entry["role_in_mission"]] = role_counts.get(entry["role_in_mission"], 0) + 1
    if any(count > 1 for count in role_counts.values()) or not required.issubset(role_counts):
        fail(ERR_CREW_COMPOSITION_INCOMPLETE, 422,
             "Crew roster does not cover the tier minimum or duplicates a role")
    # 3. every referenced member must be ACTIVE
    for entry in cleaned_crew:
        member = db.crew_members[entry["crew_member_id"]]
        if member["status"] != "ACTIVE":
            fail(ERR_CREW_UNAVAILABLE, 422,
                 "Crew member %s is not ACTIVE" % entry["crew_member_id"])
    # 4. tail must not be in MAINTENANCE (AVAILABLE or ASSIGNED both pass)
    if aircraft["status"] == "MAINTENANCE":
        fail(ERR_AIRCRAFT_NOT_AVAILABLE, 409, "Aircraft is in MAINTENANCE")
    # 5. half-open occupancy windows on the same tail must not overlap
    new_end = launch + timedelta(minutes=duration)
    for m in db.missions.values():
        if m["aircraft_id"] != aircraft_id or m["status"] in {"COMPLETED", "ABORTED", "CANCELLED"}:
            continue
        m_start = m["_planned_launch"]
        m_end = m_start + timedelta(minutes=m["planned_duration_min"])
        if _window_overlaps(launch, new_end, m_start, m_end):
            fail(ERR_AIRCRAFT_SCHEDULE_CONFLICT, 409,
                 "Planned window overlaps another non-terminal mission on this tail")

    # --- effects ------------------------------------------------------------
    req["status"] = "ACCEPTED"
    touch(req)
    mission = stamp_new({
        "mission_request_id": req["id"],
        "aircraft_id": aircraft_id,
        "transport_class": req["transport_class"],
        "acuity_tier": req["acuity_tier"],
        "destination_facility": req["destination_facility"],
        "estimated_loaded_miles": est_miles,
        "planned_launch_iso": launch_raw,
        "planned_duration_min": duration,
        "alternate_destination": alternate,
        "launched_at": None,
        "completed_at": None,
        "last_weather_decision": None,
        "ground_coordination_status": "COORDINATED",
        "status": "PLANNING",
        "_planned_launch": launch,
        "_completed_dt": None,
    })
    db.missions[mission["id"]] = mission
    # binding the tail mutates it (AVAILABLE -> ASSIGNED, or an additional
    # non-overlapping booking on an already-ASSIGNED tail)
    aircraft["status"] = "ASSIGNED"
    touch(aircraft)
    for entry in cleaned_crew:
        assignment = stamp_new({
            "mission_id": mission["id"],
            "crew_member_id": entry["crew_member_id"],
            "role_in_mission": entry["role_in_mission"],
            "status": "ASSIGNED",
        })
        db.crew_assignments[assignment["id"]] = assignment
    return ok_object(ser_mission(mission), 201)
