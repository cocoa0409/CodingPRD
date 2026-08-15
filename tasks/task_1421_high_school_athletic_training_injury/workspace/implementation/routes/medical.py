"""Routes: injuries, referrals, RTP protocols, guardian notifications."""
from datetime import timedelta

import db
from domain import (
    BODY_REGIONS, INJURY_TYPES, PROTOCOL_TYPES, REPORT_CLEARANCES,
    RESTRICTED_ACTIVITIES, SEVERITIES, URGENCIES, REFERRAL_WINDOWS,
    body_json, create_notification, get_path_resource, iso_z, new_resource,
    now_dt, now_iso_ms, opt_string, opt_string_list, parse_dt,
    posture_dependent_recompute, recompute_posture, req_enum, req_field,
    req_string, ser_injury, ser_notification, ser_protocol, ser_referral,
    set_props,
)
from errors import ApiError
from middleware import require_roles
from response import success_object
from flask import Blueprint

from routes.core import list_response, query_filter

bp = Blueprint("medical", __name__)

MEDICAL_READ_ROLES = ["SystemAdmin", "AthleticTrainer", "AthleticDirector", "SchoolNurse", "Physician"]
DWELL = timedelta(hours=24)
CLOSE_WINDOW = timedelta(days=30)


# --------------------------------------------------------------------------
# Injuries
# --------------------------------------------------------------------------
@bp.post("/injuries")
@require_roles("AthleticTrainer")
def create_injury(ctx):
    body = body_json()
    athlete_id = req_string(body, "athlete_id")
    event_id = opt_string(body, "event_id")
    body_region = req_enum(body, "body_region", BODY_REGIONS)
    injury_type = req_enum(body, "injury_type", INJURY_TYPES)
    severity = req_enum(body, "severity", SEVERITIES)
    mechanism = req_string(body, "mechanism")
    evaluated_at = parse_dt(req_field(body, "evaluated_at"), "evaluated_at")
    restricted = opt_string_list(body, "restricted_activities", default=[], allowed=RESTRICTED_ACTIVITIES)
    reopen_of_id = opt_string(body, "reopen_of_id")

    athlete = db.athletes.get(athlete_id)
    if athlete is None:
        raise ApiError("ERR_ATHLETE_NOT_FOUND", "Athlete id does not exist.")
    if event_id is not None and event_id not in db.events:
        raise ApiError("ERR_EVENT_NOT_FOUND", "Event id does not exist.")
    prior = None
    if reopen_of_id is not None:
        prior = db.injuries.get(reopen_of_id)
        if prior is None:
            raise ApiError("ERR_INJURY_NOT_FOUND", "Injury id does not exist.")
    if evaluated_at > now_dt():
        raise ApiError("ERR_INVALID_DATE_RANGE", "evaluated_at may not lie in the future.")
    if prior is not None:
        if prior["status"] != "CLOSED" or prior["athlete_id"] != athlete_id:
            raise ApiError(
                "ERR_REFERENCED_INJURY_NOT_CLOSED",
                "reopen_of_id must reference a CLOSED injury of the same athlete.",
            )

    rec = new_resource(
        {
            "athlete_id": athlete_id,
            "event_id": event_id,
            "body_region": body_region,
            "injury_type": injury_type,
            "severity": severity,
            "mechanism": mechanism,
            "evaluated_at": iso_z(evaluated_at),
            "restricted_activities": restricted,
            "reopen_of_id": reopen_of_id,
            "evaluated_by_staff_id": ctx["uid"],
            "recurrence_count": (prior["recurrence_count"] + 1) if prior is not None else 0,
            "resolved_at": None,
            "status": "OPEN",
        }
    )
    db.injuries[rec["id"]] = rec

    create_notification(athlete_id, "INJURY_INITIAL", injury_id=rec["id"])
    if injury_type == "CONCUSSION":
        for b in db.baselines.values():
            if b["athlete_id"] == athlete_id and b["status"] == "CURRENT":
                set_props(b, status="SUPERSEDED")
    recompute_posture(athlete_id)
    posture_dependent_recompute(athlete_id)
    return success_object(ser_injury(rec), 201)


@bp.get("/injuries")
@require_roles(*MEDICAL_READ_ROLES)
def list_injuries(ctx):
    filters = []
    for field in ("athlete_id", "event_id", "evaluated_by_staff_id", "reopen_of_id", "status", "injury_type"):
        f = query_filter(field)
        if f:
            filters.append(f)
    return list_response(list(db.injuries.values()), ser_injury, filters)


@bp.get("/injuries/<injuryId>")
@require_roles(*MEDICAL_READ_ROLES)
def get_injury(ctx, injuryId):
    rec = get_path_resource(
        db.injuries, injuryId, "ERR_INJURY_NOT_FOUND", "Injury id does not exist.")
    return success_object(ser_injury(rec))


@bp.post("/injuries/<injuryId>/begin-care")
@require_roles("AthleticTrainer")
def begin_care(ctx, injuryId):
    rec = get_path_resource(
        db.injuries, injuryId, "ERR_INJURY_NOT_FOUND", "Injury id does not exist.")
    if rec["status"] not in ("OPEN", "REFERRED"):
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN or REFERRED injury can begin care.")
    set_props(rec, status="UNDER_CARE")
    recompute_posture(rec["athlete_id"])
    posture_dependent_recompute(rec["athlete_id"])
    return success_object(ser_injury(rec))


@bp.post("/injuries/<injuryId>/resolve")
@require_roles("AthleticTrainer")
def resolve_injury(ctx, injuryId):
    rec = get_path_resource(
        db.injuries, injuryId, "ERR_INJURY_NOT_FOUND", "Injury id does not exist.")
    if rec["status"] != "UNDER_CARE":
        raise ApiError("ERR_INVALID_STATE", "Only an UNDER_CARE injury can be resolved.")
    if any(p["injury_id"] == injuryId and p["status"] == "ACTIVE" for p in db.protocols.values()):
        raise ApiError("ERR_INVALID_STATE", "An ACTIVE return-to-play protocol still exists for this injury.")
    set_props(rec, status="RESOLVED", resolved_at=now_iso_ms())
    recompute_posture(rec["athlete_id"])
    posture_dependent_recompute(rec["athlete_id"])
    return success_object(ser_injury(rec))


@bp.post("/injuries/<injuryId>/reopen")
@require_roles("AthleticTrainer")
def reopen_injury(ctx, injuryId):
    body = body_json()
    req_string(body, "reason")
    rec = get_path_resource(
        db.injuries, injuryId, "ERR_INJURY_NOT_FOUND", "Injury id does not exist.")
    if rec["status"] != "RESOLVED":
        raise ApiError("ERR_INVALID_STATE", "Only a RESOLVED injury can be reopened.")
    set_props(rec, status="OPEN", resolved_at=None)
    recompute_posture(rec["athlete_id"])
    posture_dependent_recompute(rec["athlete_id"])
    return success_object(ser_injury(rec))


@bp.post("/injuries/<injuryId>/close")
@require_roles("AthleticTrainer")
def close_injury(ctx, injuryId):
    rec = get_path_resource(
        db.injuries, injuryId, "ERR_INJURY_NOT_FOUND", "Injury id does not exist.")
    if rec["status"] != "RESOLVED":
        raise ApiError("ERR_INVALID_STATE", "Only a RESOLVED injury can be closed.")
    resolved_at = parse_dt(rec["resolved_at"], "resolved_at")
    if now_dt() < resolved_at + CLOSE_WINDOW:
        raise ApiError("ERR_CLOSE_WINDOW_NOT_MET", "The injury was resolved fewer than 30 days ago.")
    set_props(rec, status="CLOSED")
    return success_object(ser_injury(rec))


# --------------------------------------------------------------------------
# Physician referrals
# --------------------------------------------------------------------------
@bp.post("/referrals")
@require_roles("AthleticTrainer")
def create_referral(ctx):
    body = body_json()
    injury_id = req_string(body, "injury_id")
    physician_staff_id = req_string(body, "physician_staff_id")
    reason = req_string(body, "reason")
    urgency = req_enum(body, "urgency", URGENCIES)

    injury = db.injuries.get(injury_id)
    if injury is None:
        raise ApiError("ERR_INJURY_NOT_FOUND", "Injury id does not exist.")
    physician = db.staff.get(physician_staff_id)
    if physician is None:
        raise ApiError("ERR_STAFF_NOT_FOUND", "Staff id does not exist.")

    if injury["status"] not in ("OPEN", "UNDER_CARE", "RTP_IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE", "The injury cannot accept a new referral in its current state.")

    if physician["role_type"] != "PHYSICIAN":
        raise ApiError("ERR_STAFF_ROLE_MISMATCH", "The referral physician must have role_type PHYSICIAN.")

    created_dt = now_dt()
    rec = new_resource(
        {
            "injury_id": injury_id,
            "athlete_id": injury["athlete_id"],
            "physician_staff_id": physician_staff_id,
            "reason": reason,
            "urgency": urgency,
            "due_by": iso_z(created_dt + REFERRAL_WINDOWS[urgency]),
            "appointment_at": None,
            "report_diagnosis": None,
            "report_clearance": None,
            "reported_at": None,
            "status": "REQUESTED",
        }
    )
    db.referrals[rec["id"]] = rec

    if injury["status"] in ("OPEN", "UNDER_CARE"):
        set_props(injury, status="REFERRED")
    create_notification(injury["athlete_id"], "REFERRAL_REQUEST", injury_id=injury_id, referral_id=rec["id"])
    recompute_posture(injury["athlete_id"])
    posture_dependent_recompute(injury["athlete_id"])
    return success_object(ser_referral(rec), 201)


@bp.get("/referrals")
@require_roles(*MEDICAL_READ_ROLES)
def list_referrals(ctx):
    filters = []
    for field in ("injury_id", "athlete_id", "physician_staff_id", "status"):
        f = query_filter(field)
        if f:
            filters.append(f)
    return list_response(list(db.referrals.values()), ser_referral, filters)


@bp.get("/referrals/<referralId>")
@require_roles(*MEDICAL_READ_ROLES)
def get_referral(ctx, referralId):
    rec = get_path_resource(
        db.referrals, referralId, "ERR_REFERRAL_NOT_FOUND", "Referral id does not exist.")
    return success_object(ser_referral(rec))


@bp.post("/referrals/<referralId>/schedule")
@require_roles("AthleticTrainer")
def schedule_referral(ctx, referralId):
    body = body_json()
    appointment_at = parse_dt(req_field(body, "appointment_at"), "appointment_at")
    rec = get_path_resource(
        db.referrals, referralId, "ERR_REFERRAL_NOT_FOUND", "Referral id does not exist.")
    if rec["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Only a REQUESTED referral can be scheduled.")
    set_props(rec, status="SCHEDULED", appointment_at=iso_z(appointment_at))
    return success_object(ser_referral(rec))


def _terminate_active_protocols_for_injury(injury, reason):
    """Referral report NOT_CLEARED cascade: terminate ACTIVE protocols, injury -> UNDER_CARE."""
    now = now_iso_ms()
    for p in db.protocols.values():
        if p["injury_id"] == injury["id"] and p["status"] == "ACTIVE":
            set_props(p, status="TERMINATED",
                      stage_history=_close_stage_entry(p, now, reason))
    if injury["status"] == "RTP_IN_PROGRESS":
        if not any(p["injury_id"] == injury["id"] and p["status"] == "ACTIVE" for p in db.protocols.values()):
            set_props(injury, status="UNDER_CARE")


@bp.post("/referrals/<referralId>/complete")
@require_roles("Physician")
def complete_referral(ctx, referralId):
    rec = get_path_resource(
        db.referrals, referralId, "ERR_REFERRAL_NOT_FOUND", "Referral id does not exist.")
    if ctx["uid"] != rec["physician_staff_id"]:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", "The caller must be the physician named on the referral.")
    body = body_json()
    report_diagnosis = req_string(body, "report_diagnosis")
    report_clearance = req_enum(body, "report_clearance", REPORT_CLEARANCES)
    if rec["status"] not in ("SCHEDULED", "ADDENDUM_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED or ADDENDUM_REQUESTED referral can be completed.")
    set_props(
        rec,
        status="COMPLETED",
        report_diagnosis=report_diagnosis,
        report_clearance=report_clearance,
        reported_at=now_iso_ms(),
    )
    injury = db.injuries.get(rec["injury_id"])
    if report_clearance == "NOT_CLEARED" and injury is not None:
        _terminate_active_protocols_for_injury(injury, "TERMINATED")
    if report_clearance in ("CLEARED_FULL", "CLEARED_RESTRICTED"):
        create_notification(rec["athlete_id"], "CLEARANCE_GRANTED", injury_id=rec["injury_id"], referral_id=rec["id"])
    recompute_posture(rec["athlete_id"])
    posture_dependent_recompute(rec["athlete_id"])
    return success_object(ser_referral(rec))


@bp.post("/referrals/<referralId>/request-addendum")
@require_roles("AthleticTrainer")
def request_addendum(ctx, referralId):
    body = body_json()
    req_string(body, "question")
    rec = get_path_resource(
        db.referrals, referralId, "ERR_REFERRAL_NOT_FOUND", "Referral id does not exist.")
    if rec["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", "Only a COMPLETED referral can be sent back for an addendum.")
    set_props(rec, status="ADDENDUM_REQUESTED")
    return success_object(ser_referral(rec))


@bp.post("/referrals/<referralId>/close")
@require_roles("AthleticTrainer")
def close_referral(ctx, referralId):
    rec = get_path_resource(
        db.referrals, referralId, "ERR_REFERRAL_NOT_FOUND", "Referral id does not exist.")
    if rec["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", "Only a COMPLETED referral can be closed.")
    set_props(rec, status="CLOSED")
    return success_object(ser_referral(rec))


@bp.post("/referrals/<referralId>/cancel")
@require_roles("AthleticTrainer")
def cancel_referral(ctx, referralId):
    rec = get_path_resource(
        db.referrals, referralId, "ERR_REFERRAL_NOT_FOUND", "Referral id does not exist.")
    if rec["status"] not in ("REQUESTED", "SCHEDULED"):
        raise ApiError("ERR_INVALID_STATE", "Only a REQUESTED or SCHEDULED referral can be cancelled.")
    set_props(rec, status="CANCELLED")
    return success_object(ser_referral(rec))


# --------------------------------------------------------------------------
# Return-to-play protocols
# --------------------------------------------------------------------------
def _close_stage_entry(rec, now, reason):
    """Append a closed stage-history entry for the stage being exited
    (PRD §3.7: every transition *appends* an entry recording the stage, its
    entered_at/exited_at instants, and the exit_reason; activation itself
    appends nothing — the log opens empty)."""
    history = [dict(h) for h in rec["stage_history"]]
    history.append(
        {
            "stage": rec["current_stage"],
            "entered_at": rec["stage_entered_at"],
            "exited_at": now,
            "exit_reason": reason,
        }
    )
    return history


@bp.post("/injuries/<injuryId>/rtp-protocols")
@require_roles("AthleticTrainer")
def create_protocol(ctx, injuryId):
    injury = get_path_resource(
        db.injuries, injuryId, "ERR_INJURY_NOT_FOUND", "Injury id does not exist.")
    body = body_json()
    protocol_type = req_enum(body, "protocol_type", PROTOCOL_TYPES)
    expected = req_field(body, "expected_injury_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'expected_injury_version' must be an integer.")
    if expected != injury["version"]:
        raise ApiError("ERR_STALE_VERSION", "The injury has changed since the caller last observed it.")
    if injury["status"] not in ("UNDER_CARE", "RTP_IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE", "The injury cannot accept a new protocol in its current state.")

    authority = (
        "PHYSICIAN"
        if injury["injury_type"] == "CONCUSSION" or injury["severity"] in ("SEVERE", "CRITICAL")
        else "TRAINER"
    )
    now = now_iso_ms()

    # Supersede any ACTIVE protocol on the same injury.
    for p in db.protocols.values():
        if p["injury_id"] == injuryId and p["status"] == "ACTIVE":
            set_props(p, status="TERMINATED",
                      stage_history=_close_stage_entry(p, now, "TERMINATED"))

    rec = new_resource(
        {
            "injury_id": injuryId,
            "athlete_id": injury["athlete_id"],
            "protocol_type": protocol_type,
            "current_stage": 1,
            "stage_entered_at": now,
            "recurrence_count": 0,
            "clearance_authority_required": authority,
            "stage_history": [],
            "cleared_by_staff_id": None,
            "cleared_at": None,
            "status": "ACTIVE",
        }
    )
    db.protocols[rec["id"]] = rec

    if injury["status"] != "RTP_IN_PROGRESS":
        injury["status"] = "RTP_IN_PROGRESS"
    injury["updated_at"] = now_iso_ms()
    injury["version"] += 1

    recompute_posture(injury["athlete_id"])
    posture_dependent_recompute(injury["athlete_id"])
    return success_object(ser_protocol(rec), 201)


@bp.get("/rtp-protocols")
@require_roles(*MEDICAL_READ_ROLES)
def list_protocols(ctx):
    filters = []
    for field in ("injury_id", "athlete_id", "cleared_by_staff_id", "status"):
        f = query_filter(field)
        if f:
            filters.append(f)
    return list_response(list(db.protocols.values()), ser_protocol, filters)


@bp.get("/rtp-protocols/<protocolId>")
@require_roles(*MEDICAL_READ_ROLES)
def get_protocol(ctx, protocolId):
    rec = get_path_resource(
        db.protocols, protocolId, "ERR_PROTOCOL_NOT_FOUND", "RTP protocol id does not exist.")
    return success_object(ser_protocol(rec))


def _physician_clearance_exists(injury_id):
    return any(
        r["injury_id"] == injury_id
        and r["status"] in ("COMPLETED", "CLOSED")
        and r["report_clearance"] in ("CLEARED_FULL", "CLEARED_RESTRICTED")
        for r in db.referrals.values()
    )


@bp.post("/rtp-protocols/<protocolId>/advance")
@require_roles("AthleticTrainer")
def advance_protocol(ctx, protocolId):
    rec = get_path_resource(
        db.protocols, protocolId, "ERR_PROTOCOL_NOT_FOUND", "RTP protocol id does not exist.")
    body = body_json()
    symptom_check_passed = req_field(body, "symptom_check_passed")

    if rec["status"] != "ACTIVE" or rec["current_stage"] > 5:
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE protocol at stage 1-5 can advance.")
    if symptom_check_passed is not True:
        raise ApiError("ERR_SYMPTOMS_REPORTED", "Advance requires the athlete to be symptom-free.")
    athlete = db.athletes.get(rec["athlete_id"])
    if athlete is not None and athlete["participation_posture"] in ("INELIGIBLE", "NOT_CLEARED"):
        raise ApiError(
            "ERR_PHYSICAL_EXPIRED",
            "The athlete's participation posture blocks protocol advancement.",
        )
    injury = db.injuries.get(rec["injury_id"])
    if rec["current_stage"] == 4 and injury is not None and injury["injury_type"] == "CONCUSSION":
        if not _physician_clearance_exists(rec["injury_id"]):
            raise ApiError(
                "ERR_RTP_PHYSICIAN_REVIEW_REQUIRED",
                "Advancing a concussion protocol into stage 5 requires a completed clearing physician report.",
            )
    if rec["recurrence_count"] >= 2:
        if not _physician_clearance_exists(rec["injury_id"]):
            raise ApiError(
                "ERR_RTP_PHYSICIAN_REVIEW_REQUIRED",
                "Advancing after two recurrences requires a completed clearing physician report.",
            )
    if now_dt() < parse_dt(rec["stage_entered_at"], "stage_entered_at") + DWELL:
        raise ApiError("ERR_RTP_STAGE_DWELL_NOT_MET", "Fewer than 24 hours have elapsed in the current stage.")

    now = now_iso_ms()
    history = _close_stage_entry(rec, now, "ADVANCED")
    set_props(rec, current_stage=rec["current_stage"] + 1, stage_entered_at=now, stage_history=history)

    if injury is not None and injury["status"] == "UNDER_CARE":
        set_props(injury, status="RTP_IN_PROGRESS")
        recompute_posture(injury["athlete_id"])
        posture_dependent_recompute(injury["athlete_id"])
    return success_object(ser_protocol(rec))


@bp.post("/rtp-protocols/<protocolId>/regress")
@require_roles("AthleticTrainer")
def regress_protocol(ctx, protocolId):
    rec = get_path_resource(
        db.protocols, protocolId, "ERR_PROTOCOL_NOT_FOUND", "RTP protocol id does not exist.")
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE protocol can regress.")

    now = now_iso_ms()
    history = _close_stage_entry(rec, now, "REGRESSED")
    set_props(
        rec,
        current_stage=1,
        stage_entered_at=now,
        recurrence_count=rec["recurrence_count"] + 1,
        stage_history=history,
    )
    injury = db.injuries.get(rec["injury_id"])
    if injury is not None and injury["status"] == "RTP_IN_PROGRESS":
        set_props(injury, status="UNDER_CARE")
    create_notification(rec["athlete_id"], "RTP_REGRESSION", injury_id=rec["injury_id"])
    recompute_posture(rec["athlete_id"])
    posture_dependent_recompute(rec["athlete_id"])
    return success_object(ser_protocol(rec))


@bp.post("/rtp-protocols/<protocolId>/clear")
@require_roles("AthleticTrainer", "Physician")
def clear_protocol(ctx, protocolId):
    rec = get_path_resource(
        db.protocols, protocolId, "ERR_PROTOCOL_NOT_FOUND", "RTP protocol id does not exist.")
    body = body_json()
    req_string(body, "clearance_notes")

    if rec["status"] != "ACTIVE" or rec["current_stage"] != 6:
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE protocol at stage 6 can be cleared.")
    athlete = db.athletes.get(rec["athlete_id"])
    if athlete is not None and athlete["participation_posture"] in ("INELIGIBLE", "NOT_CLEARED"):
        raise ApiError(
            "ERR_PHYSICAL_EXPIRED",
            "The athlete's participation posture blocks protocol clearance.",
        )
    if rec["clearance_authority_required"] == "PHYSICIAN" and ctx["role"] != "Physician":
        raise ApiError(
            "ERR_CLEARANCE_AUTHORITY_INSUFFICIENT",
            "This protocol's clearance requires a Physician.",
        )
    if now_dt() < parse_dt(rec["stage_entered_at"], "stage_entered_at") + DWELL:
        raise ApiError("ERR_RTP_STAGE_DWELL_NOT_MET", "Fewer than 24 hours have elapsed in the current stage.")

    now = now_iso_ms()
    history = _close_stage_entry(rec, now, "CLEARED")
    set_props(
        rec,
        status="CLEARED",
        cleared_by_staff_id=ctx["uid"],
        cleared_at=now,
        stage_history=history,
    )
    injury = db.injuries.get(rec["injury_id"])
    if injury is not None and injury["status"] == "RTP_IN_PROGRESS":
        set_props(injury, status="RESOLVED", resolved_at=now)
    create_notification(rec["athlete_id"], "CLEARANCE_GRANTED", injury_id=rec["injury_id"])
    recompute_posture(rec["athlete_id"])
    posture_dependent_recompute(rec["athlete_id"])
    return success_object(ser_protocol(rec))


@bp.post("/rtp-protocols/<protocolId>/terminate")
@require_roles("AthleticTrainer", "Physician")
def terminate_protocol(ctx, protocolId):
    rec = get_path_resource(
        db.protocols, protocolId, "ERR_PROTOCOL_NOT_FOUND", "RTP protocol id does not exist.")
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE protocol can be terminated.")
    now = now_iso_ms()
    history = _close_stage_entry(rec, now, "TERMINATED")
    set_props(rec, status="TERMINATED", stage_history=history)
    injury = db.injuries.get(rec["injury_id"])
    if injury is not None and injury["status"] == "RTP_IN_PROGRESS":
        if not any(p["injury_id"] == injury["id"] and p["status"] == "ACTIVE" for p in db.protocols.values()):
            set_props(injury, status="UNDER_CARE")
            recompute_posture(injury["athlete_id"])
            posture_dependent_recompute(injury["athlete_id"])
    return success_object(ser_protocol(rec))


# --------------------------------------------------------------------------
# Guardian notifications
# --------------------------------------------------------------------------
def _guardian_visible(ctx, notif):
    if ctx["role"] != "ParentGuardian":
        return True
    athlete = db.athletes.get(notif["athlete_id"])
    return athlete is not None and athlete["guardian_user_id"] == ctx["uid"]


@bp.get("/guardian-notifications")
@require_roles("SystemAdmin", "AthleticTrainer", "AthleticDirector", "SchoolNurse", "Physician", "ParentGuardian")
def list_notifications(ctx):
    filters = [lambda n: _guardian_visible(ctx, n)]
    for field in ("athlete_id", "injury_id", "referral_id", "status", "notification_type"):
        f = query_filter(field)
        if f:
            filters.append(f)
    return list_response(list(db.notifications.values()), ser_notification, filters)


@bp.get("/guardian-notifications/<notificationId>")
@require_roles("SystemAdmin", "AthleticTrainer", "AthleticDirector", "SchoolNurse", "Physician", "ParentGuardian")
def get_notification(ctx, notificationId):
    rec = get_path_resource(
        db.notifications, notificationId, "ERR_NOTIFICATION_NOT_FOUND", "Guardian notification id does not exist.")
    if not _guardian_visible(ctx, rec):
        raise ApiError("ERR_OWNERSHIP_MISMATCH", "Guardians may only view their own child's notifications.")
    return success_object(ser_notification(rec))


@bp.post("/guardian-notifications/<notificationId>/send")
@require_roles("AthleticTrainer")
def send_notification(ctx, notificationId):
    rec = get_path_resource(
        db.notifications, notificationId, "ERR_NOTIFICATION_NOT_FOUND", "Guardian notification id does not exist.")
    if rec["status"] not in ("QUEUED", "FAILED"):
        raise ApiError("ERR_INVALID_STATE", "Only a QUEUED or FAILED notification can be sent.")
    athlete = db.athletes.get(rec["athlete_id"])
    if rec["channel"] == "EMAIL":
        if athlete is None or athlete.get("guardian_email") is None:
            raise ApiError("ERR_GUARDIAN_CONTACT_MISSING", "The athlete record lacks a guardian email.")
    else:
        if athlete is None or athlete.get("guardian_phone") is None:
            raise ApiError("ERR_GUARDIAN_CONTACT_MISSING", "The athlete record lacks a guardian phone.")
    if rec["channel"] == "PHONE" and athlete is not None and athlete.get("guardian_phone") == "UNREACHABLE":
        set_props(rec, status="FAILED", attempts=rec["attempts"] + 1)
    else:
        set_props(rec, status="SENT", sent_at=now_iso_ms(), attempts=rec["attempts"] + 1)
    return success_object(ser_notification(rec))


@bp.post("/guardian-notifications/<notificationId>/acknowledge")
@require_roles("ParentGuardian")
def acknowledge_notification(ctx, notificationId):
    rec = get_path_resource(
        db.notifications, notificationId, "ERR_NOTIFICATION_NOT_FOUND", "Guardian notification id does not exist.")
    athlete = db.athletes.get(rec["athlete_id"])
    if athlete is None or athlete["guardian_user_id"] != ctx["uid"]:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", "Guardians may only acknowledge their own child's notifications.")
    if rec["status"] not in ("SENT", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE", "Only a SENT or ESCALATED notification can be acknowledged.")
    set_props(rec, status="ACKNOWLEDGED", acknowledged_at=now_iso_ms())
    return success_object(ser_notification(rec))


@bp.post("/guardian-notifications/<notificationId>/retry")
@require_roles("AthleticTrainer")
def retry_notification(ctx, notificationId):
    rec = get_path_resource(
        db.notifications, notificationId, "ERR_NOTIFICATION_NOT_FOUND", "Guardian notification id does not exist.")
    if rec["status"] != "FAILED":
        raise ApiError("ERR_INVALID_STATE", "Only a FAILED notification can be requeued.")
    set_props(rec, status="QUEUED")
    return success_object(ser_notification(rec))
