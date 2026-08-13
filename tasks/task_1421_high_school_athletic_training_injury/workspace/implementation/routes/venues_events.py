"""Routes: venues, emergency action plans, events, coverage assignments, weather readings."""
from datetime import timedelta

from flask import request

import db
from domain import (
    COVERAGE_ROLES, EVENT_TYPES, READING_SOURCES, READING_TYPES, SPORTS,
    SURFACES, TEAM_LEVELS, VENUE_TYPES,
    body_json, cascade_event_cancel, cascade_event_complete,
    cascade_event_resume, cascade_event_suspension, compute_required_trainers,
    create_notification, iso_z, new_resource, now_dt, now_iso_ms, opt_bool,
    opt_enum, opt_number, opt_string, parse_dt, recompute_posture,
    posture_dependent_recompute, req_enum, req_field, req_int, req_string,
    ser_assignment, ser_eap, ser_event, ser_reading, ser_venue, set_props,
    update_event_coverage, venue_heat_tier, venue_lightning_hold_until,
    get_path_resource,
)
from errors import ApiError
from middleware import require_roles
from response import success_object
from flask import Blueprint

from routes.core import list_response, query_filter

bp = Blueprint("venues_events", __name__)

ALL_STAFF_ROLES = ["SystemAdmin", "AthleticTrainer", "AthleticDirector", "SchoolNurse", "Physician", "TeamCoach"]


# --------------------------------------------------------------------------
# Venues
# --------------------------------------------------------------------------
@bp.post("/venues")
@require_roles("SystemAdmin")
def create_venue(ctx):
    body = body_json()
    venue_name = req_string(body, "venue_name")
    venue_type = req_enum(body, "venue_type", VENUE_TYPES)
    surface = req_enum(body, "surface", SURFACES)
    address = req_string(body, "address")
    lightning_detection = opt_bool(body, "lightning_detection", False)
    radius = opt_number(body, "lightning_radius_miles", 8.0)
    if radius <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'lightning_radius_miles' must be positive.")
    is_active = opt_bool(body, "is_active", True)
    rec = new_resource(
        {
            "venue_name": venue_name,
            "venue_type": venue_type,
            "surface": surface,
            "lightning_detection": lightning_detection,
            "lightning_radius_miles": radius,
            "address": address,
            "is_active": is_active,
            "active_eap_id": None,
        }
    )
    db.venues[rec["id"]] = rec
    return success_object(ser_venue(rec), 201)


@bp.get("/venues")
@require_roles(*ALL_STAFF_ROLES)
def list_venues(ctx):
    filters = []
    f = query_filter("active_eap_id")
    if f:
        filters.append(f)
    raw_active = request.args.get("is_active")
    if raw_active is not None:
        active = raw_active.lower() in ("true", "1", "yes")
        filters.append(lambda r: r["is_active"] is active)
    return list_response(list(db.venues.values()), ser_venue, filters)


@bp.get("/venues/<venueId>")
@require_roles(*ALL_STAFF_ROLES)
def get_venue(ctx, venueId):
    rec = get_path_resource(
        db.venues, venueId, "ERR_VENUE_NOT_FOUND", "Venue id does not exist.")
    return success_object(ser_venue(rec))


@bp.get("/venues/<venueId>/activity-status")
@require_roles(*ALL_STAFF_ROLES)
def get_venue_activity_status(ctx, venueId):
    rec = get_path_resource(
        db.venues, venueId, "ERR_VENUE_NOT_FOUND", "Venue id does not exist.")
    tier = venue_heat_tier(venueId, tournament=False)
    hold_until = venue_lightning_hold_until(venueId, tournament=False)
    active = hold_until is not None and now_dt() < hold_until
    return success_object(
        {
            "venue_id": venueId,
            "current_heat_tier": tier,
            "lightning_hold_active": active,
            "lightning_hold_until": iso_z(hold_until) if hold_until is not None else None,
        }
    )


# --------------------------------------------------------------------------
# Emergency action plans
# --------------------------------------------------------------------------
@bp.post("/emergency-action-plans")
@require_roles("AthleticTrainer", "AthleticDirector")
def create_eap(ctx):
    body = body_json()
    venue_id = req_string(body, "venue_id")
    version_label = req_string(body, "version_label")
    evacuation_route = req_string(body, "evacuation_route")
    aed_location = req_string(body, "aed_location")
    ems_contact = req_string(body, "ems_contact")
    nearest_hospital = req_string(body, "nearest_hospital")
    supersedes_eap_id = opt_string(body, "supersedes_eap_id")

    venue = db.venues.get(venue_id)
    if venue is None:
        raise ApiError("ERR_VENUE_NOT_FOUND", "Venue id does not exist.")
    if supersedes_eap_id is not None and supersedes_eap_id not in db.eaps:
        raise ApiError("ERR_EAP_NOT_FOUND", "Emergency action plan id does not exist.")
    if any(
        e["venue_id"] == venue_id and e["version_label"] == version_label
        for e in db.eaps.values()
    ):
        raise ApiError("ERR_INVALID_REQUEST", "version_label must be unique per venue.")

    rec = new_resource(
        {
            "venue_id": venue_id,
            "version_label": version_label,
            "evacuation_route": evacuation_route,
            "aed_location": aed_location,
            "ems_contact": ems_contact,
            "nearest_hospital": nearest_hospital,
            "supersedes_eap_id": supersedes_eap_id,
            "authored_by_staff_id": ctx["uid"],
            "approved_by_staff_id": None,
            "status": "DRAFT",
        }
    )
    db.eaps[rec["id"]] = rec
    return success_object(ser_eap(rec), 201)


@bp.get("/emergency-action-plans")
@require_roles(*ALL_STAFF_ROLES)
def list_eaps(ctx):
    filters = []
    for field in ("venue_id", "supersedes_eap_id", "approved_by_staff_id", "authored_by_staff_id", "status"):
        f = query_filter(field)
        if f:
            filters.append(f)
    return list_response(list(db.eaps.values()), ser_eap, filters)


@bp.get("/emergency-action-plans/<eapId>")
@require_roles(*ALL_STAFF_ROLES)
def get_eap(ctx, eapId):
    rec = get_path_resource(
        db.eaps, eapId, "ERR_EAP_NOT_FOUND", "Emergency action plan id does not exist.")
    return success_object(ser_eap(rec))


@bp.post("/emergency-action-plans/<eapId>/submit")
@require_roles("AthleticTrainer")
def submit_eap(ctx, eapId):
    rec = get_path_resource(
        db.eaps, eapId, "ERR_EAP_NOT_FOUND", "Emergency action plan id does not exist.")
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT plan can be submitted.")
    set_props(rec, status="PENDING_APPROVAL")
    return success_object(ser_eap(rec))


@bp.post("/emergency-action-plans/<eapId>/approve")
@require_roles("AthleticDirector")
def approve_eap(ctx, eapId):
    rec = get_path_resource(
        db.eaps, eapId, "ERR_EAP_NOT_FOUND", "Emergency action plan id does not exist.")
    if rec["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_INVALID_STATE", "Only a PENDING_APPROVAL plan can be approved.")
    if ctx["uid"] == rec["authored_by_staff_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The approver may not be the plan's author.",
        )
    set_props(rec, status="APPROVED", approved_by_staff_id=ctx["uid"])
    return success_object(ser_eap(rec))


@bp.post("/emergency-action-plans/<eapId>/reject")
@require_roles("AthleticDirector")
def reject_eap(ctx, eapId):
    rec = get_path_resource(
        db.eaps, eapId, "ERR_EAP_NOT_FOUND", "Emergency action plan id does not exist.")
    if rec["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_INVALID_STATE", "Only a PENDING_APPROVAL plan can be rejected.")
    set_props(rec, status="DRAFT")
    return success_object(ser_eap(rec))


@bp.post("/emergency-action-plans/<eapId>/activate")
@require_roles("AthleticDirector")
def activate_eap(ctx, eapId):
    body = body_json()
    rec = get_path_resource(
        db.eaps, eapId, "ERR_EAP_NOT_FOUND", "Emergency action plan id does not exist.")
    venue = db.venues.get(rec["venue_id"])
    if venue is None:
        raise ApiError("ERR_VENUE_NOT_FOUND", "Venue id does not exist.")
    expected = req_field(body, "expected_venue_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'expected_venue_version' must be an integer.")
    if expected != venue["version"]:
        raise ApiError("ERR_STALE_VERSION", "The venue has changed since the caller last observed it.")
    if rec["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED plan can be activated.")
    for other in db.eaps.values():
        if other["venue_id"] == venue["id"] and other["status"] == "ACTIVE" and other["id"] != rec["id"]:
            set_props(other, status="SUPERSEDED")
    set_props(rec, status="ACTIVE")
    venue["active_eap_id"] = rec["id"]
    venue["updated_at"] = now_iso_ms()
    venue["version"] += 1
    return success_object(ser_eap(rec))


# --------------------------------------------------------------------------
# Athletic events
# --------------------------------------------------------------------------
@bp.post("/events")
@require_roles("AthleticTrainer", "AthleticDirector")
def create_event(ctx):
    body = body_json()
    event_name = req_string(body, "event_name")
    sport = req_enum(body, "sport", SPORTS)
    team_level = req_enum(body, "team_level", TEAM_LEVELS)
    event_type = req_enum(body, "event_type", EVENT_TYPES)
    venue_id = req_string(body, "venue_id")
    start = parse_dt(req_field(body, "scheduled_start"), "scheduled_start")
    end = parse_dt(req_field(body, "scheduled_end"), "scheduled_end")
    attendance = req_int(body, "expected_attendance")
    if attendance < 0:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'expected_attendance' must be >= 0.")
    if end <= start:
        raise ApiError("ERR_INVALID_DATE_RANGE", "scheduled_end must be strictly after scheduled_start.")

    venue = db.venues.get(venue_id)
    if venue is None:
        raise ApiError("ERR_VENUE_NOT_FOUND", "Venue id does not exist.")

    buffer = timedelta(minutes=30)
    for other in db.events.values():
        if other["venue_id"] == venue_id and other["status"] != "CANCELLED":
            o_start = parse_dt(other["scheduled_start"], "scheduled_start")
            o_end = parse_dt(other["scheduled_end"], "scheduled_end")
            if start < o_end + buffer and end > o_start - buffer:
                raise ApiError(
                    "ERR_VENUE_OVERLAP",
                    "Venue already hosts a non-CANCELLED event whose 30-minute-buffered window collides.",
                )

    if not venue["is_active"]:
        raise ApiError("ERR_VENUE_INACTIVE", "New events cannot be scheduled at an inactive venue.")

    rec = new_resource(
        {
            "event_name": event_name,
            "sport": sport,
            "team_level": team_level,
            "event_type": event_type,
            "venue_id": venue_id,
            "scheduled_start": iso_z(start),
            "scheduled_end": iso_z(end),
            "expected_attendance": attendance,
            "required_trainer_count": 1,
            "active_assignment_count": 0,
            "status": "SCHEDULED",
            "suspension_reason": None,
        }
    )
    rec["required_trainer_count"] = compute_required_trainers(rec)
    db.events[rec["id"]] = rec
    return success_object(ser_event(rec), 201)


@bp.get("/events")
@require_roles(*ALL_STAFF_ROLES)
def list_events(ctx):
    filters = []
    for field in ("venue_id", "status", "sport"):
        f = query_filter(field)
        if f:
            filters.append(f)
    return list_response(list(db.events.values()), ser_event, filters)


@bp.get("/events/<eventId>")
@require_roles(*ALL_STAFF_ROLES)
def get_event(ctx, eventId):
    rec = get_path_resource(
        db.events, eventId, "ERR_EVENT_NOT_FOUND", "Event id does not exist.")
    return success_object(ser_event(rec))


@bp.get("/events/<eventId>/coverage-status")
@require_roles(*ALL_STAFF_ROLES)
def get_event_coverage(ctx, eventId):
    rec = get_path_resource(
        db.events, eventId, "ERR_EVENT_NOT_FOUND", "Event id does not exist.")
    return success_object(
        {
            "event_id": eventId,
            "required_trainer_count": rec["required_trainer_count"],
            "active_assignment_count": rec["active_assignment_count"],
            "is_covered": rec["active_assignment_count"] >= rec["required_trainer_count"],
        }
    )


@bp.post("/events/<eventId>/start")
@require_roles("AthleticTrainer")
def start_event(ctx, eventId):
    rec = get_path_resource(
        db.events, eventId, "ERR_EVENT_NOT_FOUND", "Event id does not exist.")
    if rec["status"] != "COVERED":
        raise ApiError("ERR_INVALID_STATE", "Only a COVERED event can be started.")
    venue = db.venues.get(rec["venue_id"])
    if venue is None or venue["active_eap_id"] is None:
        raise ApiError("ERR_NO_ACTIVE_EAP", "Event start requires an ACTIVE emergency action plan at the venue.")
    tournament = rec["event_type"] == "TOURNAMENT"
    if venue["venue_type"] == "OUTDOOR" and venue_heat_tier(venue["id"], tournament) == "EXTREME":
        raise ApiError("ERR_HEAT_TIER_EXTREME", "Outdoor event start is blocked while the heat tier is EXTREME.")
    hold_until = venue_lightning_hold_until(venue["id"], tournament)
    if hold_until is not None and now_dt() < hold_until:
        raise ApiError("ERR_LIGHTNING_HOLD_ACTIVE", "Event start is blocked while a lightning hold is active.")
    set_props(rec, status="IN_PROGRESS")
    return success_object(ser_event(rec))


@bp.post("/events/<eventId>/suspend")
@require_roles("AthleticTrainer")
def suspend_event(ctx, eventId):
    rec = get_path_resource(
        db.events, eventId, "ERR_EVENT_NOT_FOUND", "Event id does not exist.")
    if rec["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Only an IN_PROGRESS event can be suspended.")
    set_props(rec, status="SUSPENDED_WEATHER", suspension_reason="MANUAL")
    cascade_event_suspension(rec, "MANUAL")
    return success_object(ser_event(rec))


@bp.post("/events/<eventId>/resume")
@require_roles("AthleticTrainer")
def resume_event(ctx, eventId):
    rec = get_path_resource(
        db.events, eventId, "ERR_EVENT_NOT_FOUND", "Event id does not exist.")
    if rec["status"] != "SUSPENDED_WEATHER":
        raise ApiError("ERR_INVALID_STATE", "Only a SUSPENDED_WEATHER event can be resumed.")
    tournament = rec["event_type"] == "TOURNAMENT"
    if rec["suspension_reason"] == "LIGHTNING":
        hold_until = venue_lightning_hold_until(rec["venue_id"], tournament)
        if hold_until is not None and now_dt() < hold_until:
            raise ApiError("ERR_LIGHTNING_HOLD_ACTIVE", "The lightning hold is still active.")
    elif rec["suspension_reason"] == "HEAT":
        venue = db.venues.get(rec["venue_id"])
        if venue is not None and venue_heat_tier(venue["id"], tournament) == "EXTREME":
            raise ApiError("ERR_HEAT_TIER_EXTREME", "The venue's heat tier is still EXTREME.")
    set_props(rec, status="IN_PROGRESS", suspension_reason=None)
    cascade_event_resume(rec)
    return success_object(ser_event(rec))


@bp.post("/events/<eventId>/complete")
@require_roles("AthleticTrainer")
def complete_event(ctx, eventId):
    rec = get_path_resource(
        db.events, eventId, "ERR_EVENT_NOT_FOUND", "Event id does not exist.")
    if rec["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Only an IN_PROGRESS event can be completed.")
    set_props(rec, status="COMPLETED")
    cascade_event_complete(rec)
    return success_object(ser_event(rec))


@bp.post("/events/<eventId>/cancel")
@require_roles("AthleticTrainer", "AthleticDirector")
def cancel_event(ctx, eventId):
    rec = get_path_resource(
        db.events, eventId, "ERR_EVENT_NOT_FOUND", "Event id does not exist.")
    if rec["status"] not in ("SCHEDULED", "COVERED", "SUSPENDED_WEATHER"):
        raise ApiError("ERR_INVALID_STATE", "This event can no longer be cancelled.")
    set_props(rec, status="CANCELLED")
    cascade_event_cancel(rec)
    return success_object(ser_event(rec))


# --------------------------------------------------------------------------
# Coverage assignments
# --------------------------------------------------------------------------
@bp.post("/coverage-assignments")
@require_roles("AthleticTrainer", "AthleticDirector")
def create_assignment(ctx):
    body = body_json()
    event_id = req_string(body, "event_id")
    staff_id = req_string(body, "staff_id")
    coverage_role = req_enum(body, "coverage_role", COVERAGE_ROLES)

    event = db.events.get(event_id)
    if event is None:
        raise ApiError("ERR_EVENT_NOT_FOUND", "Event id does not exist.")
    staff = db.staff.get(staff_id)
    if staff is None:
        raise ApiError("ERR_STAFF_NOT_FOUND", "Staff id does not exist.")

    if event["status"] not in ("SCHEDULED", "COVERED"):
        raise ApiError("ERR_INVALID_STATE", "The event is not accepting new coverage assignments.")

    if coverage_role == "PRIMARY":
        start = parse_dt(event["scheduled_start"], "scheduled_start")
        end = parse_dt(event["scheduled_end"], "scheduled_end")
        for other in db.assignments.values():
            if (
                other["staff_id"] == staff_id
                and other["coverage_role"] == "PRIMARY"
                and other["status"] in ("ASSIGNED", "ACKNOWLEDGED", "ON_SITE", "ON_HOLD")
                and other["event_id"] != event_id
            ):
                other_event = db.events.get(other["event_id"])
                if other_event is None or other_event["status"] == "CANCELLED":
                    continue
                o_start = parse_dt(other_event["scheduled_start"], "scheduled_start")
                o_end = parse_dt(other_event["scheduled_end"], "scheduled_end")
                if start < o_end and o_start < end:
                    raise ApiError(
                        "ERR_COVERAGE_OVERLAP",
                        "Trainer already holds a PRIMARY assignment on an overlapping event.",
                    )

    if staff["role_type"] != "ATHLETIC_TRAINER" or not staff["is_active"]:
        raise ApiError(
            "ERR_STAFF_ROLE_MISMATCH",
            "Coverage assignee must be an active ATHLETIC_TRAINER.",
        )

    rec = new_resource(
        {
            "event_id": event_id,
            "staff_id": staff_id,
            "coverage_role": coverage_role,
            "status": "ASSIGNED",
            "pre_hold_status": None,
            "acknowledged_at": None,
            "checked_in_at": None,
        }
    )
    db.assignments[rec["id"]] = rec
    update_event_coverage(event)
    return success_object(ser_assignment(rec), 201)


@bp.get("/coverage-assignments")
@require_roles(*ALL_STAFF_ROLES)
def list_assignments(ctx):
    filters = []
    for field in ("event_id", "staff_id", "status"):
        f = query_filter(field)
        if f:
            filters.append(f)
    return list_response(list(db.assignments.values()), ser_assignment, filters)


@bp.get("/coverage-assignments/<assignmentId>")
@require_roles(*ALL_STAFF_ROLES)
def get_assignment(ctx, assignmentId):
    rec = get_path_resource(
        db.assignments, assignmentId, "ERR_NOT_FOUND", "Coverage assignment id does not exist.")
    return success_object(ser_assignment(rec))


def _get_assignment_for_self_service(ctx, assignmentId):
    rec = get_path_resource(
        db.assignments, assignmentId, "ERR_NOT_FOUND", "Coverage assignment id does not exist.")
    if ctx["uid"] != rec["staff_id"]:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", "The caller must be the assignment's trainer.")
    return rec


@bp.post("/coverage-assignments/<assignmentId>/acknowledge")
@require_roles("AthleticTrainer")
def acknowledge_assignment(ctx, assignmentId):
    rec = _get_assignment_for_self_service(ctx, assignmentId)
    if rec["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE", "Only an ASSIGNED assignment can be acknowledged.")
    set_props(rec, status="ACKNOWLEDGED", acknowledged_at=now_iso_ms())
    return success_object(ser_assignment(rec))


@bp.post("/coverage-assignments/<assignmentId>/decline")
@require_roles("AthleticTrainer")
def decline_assignment(ctx, assignmentId):
    rec = _get_assignment_for_self_service(ctx, assignmentId)
    if rec["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE", "Only an ASSIGNED assignment can be declined.")
    set_props(rec, status="DECLINED")
    event = db.events.get(rec["event_id"])
    if event is not None:
        update_event_coverage(event)
    return success_object(ser_assignment(rec))


@bp.post("/coverage-assignments/<assignmentId>/check-in")
@require_roles("AthleticTrainer")
def check_in_assignment(ctx, assignmentId):
    rec = _get_assignment_for_self_service(ctx, assignmentId)
    if rec["status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_INVALID_STATE", "Only an ACKNOWLEDGED assignment can be checked in.")
    set_props(rec, status="ON_SITE", checked_in_at=now_iso_ms())
    return success_object(ser_assignment(rec))


@bp.post("/coverage-assignments/<assignmentId>/complete")
@require_roles("AthleticTrainer")
def complete_assignment(ctx, assignmentId):
    rec = get_path_resource(
        db.assignments, assignmentId, "ERR_NOT_FOUND", "Coverage assignment id does not exist.")
    if rec["status"] not in ("ON_SITE", "ACKNOWLEDGED"):
        raise ApiError("ERR_INVALID_STATE", "Only an ON_SITE or ACKNOWLEDGED assignment can be completed.")
    set_props(rec, status="COMPLETED")
    return success_object(ser_assignment(rec))


@bp.post("/coverage-assignments/<assignmentId>/cancel")
@require_roles("AthleticTrainer", "AthleticDirector")
def cancel_assignment(ctx, assignmentId):
    rec = get_path_resource(
        db.assignments, assignmentId, "ERR_NOT_FOUND", "Coverage assignment id does not exist.")
    if rec["status"] not in ("ASSIGNED", "ACKNOWLEDGED"):
        raise ApiError("ERR_INVALID_STATE", "Only an ASSIGNED or ACKNOWLEDGED assignment can be cancelled.")
    set_props(rec, status="CANCELLED")
    event = db.events.get(rec["event_id"])
    if event is not None:
        update_event_coverage(event)
    return success_object(ser_assignment(rec))


# --------------------------------------------------------------------------
# Weather readings
# --------------------------------------------------------------------------
@bp.post("/weather-readings")
@require_roles("AthleticTrainer", "SystemAdmin")
def create_reading(ctx):
    body = body_json()
    venue_id = req_string(body, "venue_id")
    reading_type = req_enum(body, "reading_type", READING_TYPES)
    recorded_at = parse_dt(req_field(body, "recorded_at"), "recorded_at")
    source = req_enum(body, "source", READING_SOURCES)
    value_wbgt_f = opt_number(body, "value_wbgt_f")
    strike_distance_miles = opt_number(body, "strike_distance_miles")

    if reading_type == "HEAT_WBGT" and value_wbgt_f is None:
        raise ApiError("ERR_INVALID_REQUEST", "value_wbgt_f is required for HEAT_WBGT readings.")
    if reading_type == "LIGHTNING_STRIKE":
        if strike_distance_miles is None:
            raise ApiError("ERR_INVALID_REQUEST", "strike_distance_miles is required for LIGHTNING_STRIKE readings.")
        if strike_distance_miles < 0:
            raise ApiError("ERR_INVALID_REQUEST", "strike_distance_miles must be >= 0.")

    venue = db.venues.get(venue_id)
    if venue is None:
        raise ApiError("ERR_VENUE_NOT_FOUND", "Venue id does not exist.")
    if recorded_at > now_dt():
        raise ApiError("ERR_INVALID_DATE_RANGE", "recorded_at may not lie in the future.")

    rec = new_resource(
        {
            "venue_id": venue_id,
            "reading_type": reading_type,
            "value_wbgt_f": value_wbgt_f if reading_type == "HEAT_WBGT" else None,
            "strike_distance_miles": strike_distance_miles if reading_type == "LIGHTNING_STRIKE" else None,
            "recorded_at": iso_z(recorded_at),
            "source": source,
        },
        common=False,
    )
    db.readings[rec["id"]] = rec

    # Automatic weather suspensions.
    suspend_reason = None
    if reading_type == "LIGHTNING_STRIKE" and float(strike_distance_miles) <= float(venue["lightning_radius_miles"]):
        suspend_reason = "LIGHTNING"
    elif (
        reading_type == "HEAT_WBGT"
        and venue["venue_type"] == "OUTDOOR"
        and venue_heat_tier(venue_id, tournament=False) == "EXTREME"
    ):
        suspend_reason = "HEAT"

    if suspend_reason is not None:
        for event in db.events.values():
            if event["venue_id"] == venue_id and event["status"] == "IN_PROGRESS":
                if suspend_reason == "HEAT":
                    tier = venue_heat_tier(venue_id, tournament=(event["event_type"] == "TOURNAMENT"))
                    if tier != "EXTREME":
                        continue
                set_props(event, status="SUSPENDED_WEATHER", suspension_reason=suspend_reason)
                cascade_event_suspension(event, suspend_reason)

    return success_object(ser_reading(rec), 201)


@bp.get("/weather-readings")
@require_roles(*ALL_STAFF_ROLES)
def list_readings(ctx):
    filters = []
    for field in ("venue_id", "reading_type"):
        f = query_filter(field)
        if f:
            filters.append(f)
    return list_response(list(db.readings.values()), ser_reading, filters)


@bp.get("/weather-readings/<readingId>")
@require_roles(*ALL_STAFF_ROLES)
def get_reading(ctx, readingId):
    rec = get_path_resource(
        db.readings, readingId, "ERR_NOT_FOUND", "Environmental reading id does not exist.")
    return success_object(ser_reading(rec))
