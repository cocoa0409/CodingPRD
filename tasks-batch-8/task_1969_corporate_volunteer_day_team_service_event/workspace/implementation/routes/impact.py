"""ImpactRecord endpoints: nonprofit submission, CEM moderation."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_err,
    ERR_IMPACT_RECORD_NOT_FOUND,
    ERR_REGISTRATION_NOT_FOUND,
    ERR_PROJECT_NOT_FOUND,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_IMPACT_TRANSITION,
    ERR_MEDIA_CONSENT_MISSING,
    ERR_IMPACT_PROJECT_MISMATCH,
    ERR_REGISTRATION_NOT_CHECKED_IN,
    ERR_VALIDATION,
)
from middleware import authenticate, body
from response import success_object, success_list
from services import calc
from services.core import mint, bump, refresh_event, ser_impact, sort_entities
from validate import req_string, req_number, opt_int, opt_string, check_range

bp = Blueprint("impact", __name__)


def load_record(record_id):
    rec = db.impacts.get(record_id)
    if rec is None:
        raise_err(ERR_IMPACT_RECORD_NOT_FOUND, "impact record not found")
    return rec


def _touch_event(rec):
    ev = db.events.get(rec["event_id"])
    if ev is not None:
        refresh_event(ev)


@bp.post("/impact-records")
def create_impact():
    uid, _, _ = authenticate(["NonprofitCoordinator"])
    data = body()
    registration_id = req_string(data, "registration_id")
    project_id = req_string(data, "project_id")
    hours = req_number(data, "hours_attended")
    photo_count = opt_int(data, "photo_count", 0)
    story_text = opt_string(data, "story_text", "")
    # body FK existence (step 5)
    reg = db.registrations.get(registration_id)
    if reg is None:
        raise_err(ERR_REGISTRATION_NOT_FOUND, "registration not found")
    project = db.projects.get(project_id)
    if project is None:
        raise_err(ERR_PROJECT_NOT_FOUND, "service project not found")
    # ownership (step 2): coordinator owns the project's nonprofit
    if project["nonprofit_id"] != uid:
        raise_err(ERR_FORBIDDEN_ROLE, "coordinator may only submit records for their own nonprofit's projects")
    ev = db.events.get(reg["event_id"])
    # field range (step 11): hours in (0, scheduled hours]; photo_count >= 0
    scheduled = calc.scheduled_hours(ev) if ev is not None else 0
    check_range(hours > 0, "hours_attended must be > 0")
    check_range(hours <= scheduled, "hours_attended must not exceed the event's scheduled hours")
    check_range(photo_count >= 0, "photo_count must be >= 0")
    # cross-reference (step 12)
    if project["id"] != reg["project_id"]:
        raise_err(ERR_IMPACT_PROJECT_MISMATCH, "project_id differs from the registration's project")
    if reg["rsvp_status"] != "CHECKED_IN":
        raise_err(ERR_REGISTRATION_NOT_CHECKED_IN, "registration must be CHECKED_IN")
    rec = mint()
    rec.update(
        {
            "registration_id": reg["id"],
            "project_id": project["id"],
            "event_id": reg["event_id"],
            "hours_attended": calc.hours_1dp(hours),
            "photo_count": photo_count,
            "story_text": story_text,
            "status": "SUBMITTED",
            "rejection_reason": None,
        }
    )
    db.impacts[rec["id"]] = rec
    return success_object(ser_impact(rec), 201)


@bp.get("/impact-records")
def list_impacts():
    authenticate(["Any"])
    items = list(db.impacts.values())
    for param in ("registration_id", "project_id", "event_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [r for r in items if str(r.get(param)) == val]
    return success_list([ser_impact(r) for r in sort_entities(items)])


@bp.get("/impact-records/<recordId>")
def get_impact(recordId):
    authenticate(["Any"])
    return success_object(ser_impact(load_record(recordId)))


@bp.post("/impact-records/<recordId>/verify")
def verify_impact(recordId):
    authenticate(["CommunityEngagementManager"])
    rec = load_record(recordId)
    if rec["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_IMPACT_TRANSITION, "only a SUBMITTED record can be verified")
    rec["status"] = "VERIFIED"
    bump(rec)
    _touch_event(rec)
    reg = db.registrations.get(rec["registration_id"])
    if reg is not None:
        from services.core import touch

        touch(reg)
    return success_object(ser_impact(rec))


@bp.post("/impact-records/<recordId>/publish")
def publish_impact(recordId):
    authenticate(["CommunityEngagementManager"])
    rec = load_record(recordId)
    if rec["status"] != "VERIFIED":
        raise_err(ERR_INVALID_IMPACT_TRANSITION, "only a VERIFIED record can be published")
    if rec["photo_count"] > 0 or rec["story_text"] != "":
        reg = db.registrations.get(rec["registration_id"])
        if reg is None or not reg["media_consent"]:
            raise_err(ERR_MEDIA_CONSENT_MISSING, "media consent is required to publish photos or stories")
    rec["status"] = "PUBLISHED"
    bump(rec)
    return success_object(ser_impact(rec))


@bp.post("/impact-records/<recordId>/reject")
def reject_impact(recordId):
    authenticate(["CommunityEngagementManager"])
    rec = load_record(recordId)
    if rec["status"] not in ("SUBMITTED", "VERIFIED"):
        raise_err(ERR_INVALID_IMPACT_TRANSITION, "record cannot be rejected from its current status")
    was_verified = rec["status"] == "VERIFIED"
    rec["status"] = "REJECTED"
    rec["rejection_reason"] = opt_string(body(), "rejection_reason")
    bump(rec)
    if was_verified:
        _touch_event(rec)
        reg = db.registrations.get(rec["registration_id"])
        if reg is not None:
            from services.core import touch

            touch(reg)
    return success_object(ser_impact(rec))


@bp.post("/impact-records/<recordId>/resubmit")
def resubmit_impact(recordId):
    uid, _, _ = authenticate(["NonprofitCoordinator"])
    rec = load_record(recordId)
    project = db.projects.get(rec["project_id"])
    if project is None or project["nonprofit_id"] != uid:
        raise_err(ERR_FORBIDDEN_ROLE, "coordinator may only resubmit their own nonprofit's records")
    if rec["status"] != "REJECTED":
        raise_err(ERR_INVALID_IMPACT_TRANSITION, "only a REJECTED record can be resubmitted")
    rec["status"] = "SUBMITTED"
    rec["rejection_reason"] = None
    bump(rec)
    return success_object(ser_impact(rec))
