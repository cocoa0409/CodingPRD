"""Weather observations, the closure cascade, and the incident review chain."""
from datetime import timedelta

from flask import Blueprint, g

from db import store, base_row, touch, clock_now, by_created_at
from errors import ApiError, invalid
from middleware import authorize
from response import object_response, created_response, list_response, pagination, paginate
from validation import body, req_str, req_enum, req_bool, req_num, req_instant
from services import constants as C
from services import derive, serialize, cascade
from services.lookup import (get_course, get_element, get_facilitator, get_participant,
                             get_incident, get_observation, apply_filters)

bp = Blueprint("observations", __name__)
PREFIX = "/challenge-course"

WEATHER_ROLES = ["Facilitator", "SafetyOfficer", "ProgramDirector"]
READ_ROLES = ["ProgramDirector", "SafetyOfficer", "Facilitator"]
HOLD = timedelta(minutes=C.LIGHTNING_HOLD_MINUTES)


# ----------------------------------------------------------- weather observations

@bp.post(PREFIX + "/weather-observations")
def create_observation():
    authorize(WEATHER_ROLES)
    payload = body()

    course_id = req_str(payload, "course_id")
    observed_at = req_instant(payload, "observed_at")
    lightning_distance_km = req_num(payload, "lightning_distance_km", required=False, default=None)
    wind_speed_kph = req_num(payload, "wind_speed_kph", minimum=0)
    air_temp_c = req_num(payload, "air_temp_c")

    if observed_at > clock_now():
        raise invalid("observed_at may not be later than the logical clock.")

    course = get_course(course_id)

    row = base_row(common_fields=False)
    row.update({
        "course_id": course["id"],
        "observed_at": observed_at,
        "lightning_distance_km": lightning_distance_km,
        "wind_speed_kph": wind_speed_kph,
        "air_temp_c": air_temp_c,
        "resulting_posture": course["posture"],
        "resulting_posture_reason": course["posture_reason"],
        "hold_until": None,
    })
    # The row must be visible before posture is derived: posture reads the newest
    # observation for the site.
    store.weather_observations[row["id"]] = row

    triggered_hold = None
    if lightning_distance_km is not None and lightning_distance_km <= C.LIGHTNING_STOP_KM:
        candidate = observed_at + HOLD
        existing = course["lightning_hold_until"]
        # A later, farther strike never shortens an existing hold.
        course["lightning_hold_until"] = (candidate if existing is None
                                          else max(existing, candidate))
        triggered_hold = course["lightning_hold_until"]

    derive.recompute_posture(course, bump_version=True)

    if course["posture"] == "CLOSED":
        cascade.cascade_weather_closed(course)

    row["resulting_posture"] = course["posture"]
    row["resulting_posture_reason"] = course["posture_reason"]
    row["hold_until"] = triggered_hold

    return created_response(serialize.weather_observation(row))


@bp.get(PREFIX + "/weather-observations/<observation_id>")
def read_observation(observation_id):
    authorize(READ_ROLES)
    row = get_observation(observation_id)
    return object_response(serialize.weather_observation(row))


@bp.get(PREFIX + "/weather-observations")
def list_observations():
    authorize(READ_ROLES)
    limit, offset = pagination()
    rows = by_created_at(list(store.weather_observations.values()))
    rows = apply_filters(rows, {
        "course_id": ("str", "course_id"),
        "resulting_posture": ("str", "resulting_posture"),
    })
    window, total = paginate(rows, limit, offset)
    return list_response([serialize.weather_observation(r) for r in window], limit, offset, total)


# ---------------------------------------------------------------------- incidents

@bp.post(PREFIX + "/incidents")
def create_incident():
    authorize(["Facilitator", "SafetyOfficer"])
    payload = body()

    course_id = req_str(payload, "course_id")
    reporter_id = req_str(payload, "reported_by_facilitator_id")
    occurred_at = req_instant(payload, "occurred_at")
    severity = req_enum(payload, "severity", C.SEVERITIES)
    narrative = req_str(payload, "narrative")
    ems_activated = req_bool(payload, "ems_activated")
    element_id = req_str(payload, "element_id", required=False, default=None)
    participant_id = req_str(payload, "participant_id", required=False, default=None)

    if occurred_at > clock_now():
        raise invalid("occurred_at may not be later than the logical clock.")

    # Step 6 — foreign keys in declared field order.
    course = get_course(course_id)
    reporter = get_facilitator(reporter_id)
    element = get_element(element_id) if element_id else None
    participant = get_participant(participant_id) if participant_id else None

    row = base_row()
    row.update({
        "course_id": course["id"],
        "element_id": element["id"] if element is not None else None,
        "participant_id": participant["id"] if participant is not None else None,
        "reported_by_facilitator_id": reporter["id"],
        "occurred_at": occurred_at,
        "severity": severity,
        "narrative": narrative,
        "ems_activated": ems_activated,
        "status": "UNDER_REVIEW" if severity in ("MODERATE", "SERIOUS") else "REPORTED",
        "corrective_action": "NONE",
    })
    store.incidents[row["id"]] = row

    if severity == "SERIOUS" and element is not None and element["status"] == "SERVICEABLE":
        # The restriction carries no restricting log: an incident, not a defect.
        cascade.element_to_restricted(element, restricting_log_id=None)

    derive.recompute_posture(course, bump_version=(severity == "SERIOUS"))
    return created_response(serialize.incident(row))


@bp.get(PREFIX + "/incidents/<incident_id>")
def read_incident(incident_id):
    authorize(READ_ROLES)
    row = get_incident(incident_id)
    return object_response(serialize.incident(row))


@bp.get(PREFIX + "/incidents")
def list_incidents():
    authorize(READ_ROLES)
    limit, offset = pagination()
    rows = by_created_at(list(store.incidents.values()))
    rows = apply_filters(rows, {
        "course_id": ("str", "course_id"),
        "element_id": ("str", "element_id"),
        "participant_id": ("str", "participant_id"),
        "reported_by_facilitator_id": ("str", "reported_by_facilitator_id"),
        "status": ("str", "status"),
        "severity": ("str", "severity"),
    })
    window, total = paginate(rows, limit, offset)
    return list_response([serialize.incident(r) for r in window], limit, offset, total)


@bp.post(PREFIX + "/incidents/<incident_id>/review")
def review_incident(incident_id):
    authorize(["SafetyOfficer"])
    body()

    incident = get_incident(incident_id)

    # Step 9.
    if incident["status"] != "REPORTED":
        raise ApiError("ERR_INCIDENT_NOT_REPORTED")

    incident["status"] = "UNDER_REVIEW"
    touch(incident)

    course = store.courses.get(incident["course_id"])
    if course is not None:
        derive.recompute_posture(course, bump_version=False)
    return object_response(serialize.incident(incident))


@bp.post(PREFIX + "/incidents/<incident_id>/close")
def close_incident(incident_id):
    authorize(["SafetyOfficer"])
    payload = body()
    disposition = req_enum(payload, "disposition", C.DISPOSITIONS)
    corrective_action = req_enum(payload, "corrective_action", C.CORRECTIVE_ACTIONS,
                                 required=False, default=None)

    incident = get_incident(incident_id)

    # Step 9.
    if incident["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INCIDENT_NOT_UNDER_REVIEW")

    # Step 10 — the reporter may not close their own report.
    if incident["reported_by_facilitator_id"] == g.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    element = store.elements.get(incident["element_id"]) if incident["element_id"] else None

    if disposition == "CORRECTIVE":
        if corrective_action is None:
            raise invalid("A corrective close requires a corrective_action.")
        if element is None:
            raise invalid("A corrective close requires an incident naming an element.")

        incident["status"] = "CLOSED_CORRECTIVE"
        incident["corrective_action"] = corrective_action
        touch(incident)

        if corrective_action == "ELEMENT_RESTRICTED":
            if element["status"] == "SERVICEABLE":
                cascade.element_to_restricted(element, restricting_log_id=None)
        else:
            was_ready = derive.belay_ready(element)
            cascade.quarantine_rigged_equipment(element)
            cascade.propagate_belay_loss(element, was_ready)
    else:
        incident["status"] = "CLOSED_NO_ACTION"
        touch(incident)

    course = store.courses.get(incident["course_id"])
    if course is not None:
        derive.recompute_posture(course, bump_version=True)
    return object_response(serialize.incident(incident))
