from flask import Blueprint

import errors
from db import db, new_id, iso_now_ms
from clock import clock
from middleware import authenticate, require_roles
from response import success_object, success_array
from services.common import (
    get_json_body, require_str, require_enum, stamp_create, touch,
    parse_pagination, paginate, sort_by_created, parse_iso,
)
from services.compute import serialize_date_event
from services.calendar import date_overlaps_existing

bp = Blueprint("date_events", __name__)

ALL_ROLES = ("BillingAdmin", "Matchmaker", "ScreeningOfficer", "Member")


def _get_intro_or_404(intro_id):
    i = db.introductions.get(intro_id)
    if not i:
        raise errors.not_found("ERR_INTRODUCTION_NOT_FOUND")
    return i


def _get_date_or_404(date_id):
    d = db.date_events.get(date_id)
    if not d:
        raise errors.not_found("ERR_DATE_NOT_FOUND")
    return d


@bp.route("/introductions/<intro_id>/date-events", methods=["POST"])
def schedule_date(intro_id):
    principal = authenticate()
    require_roles(principal, ("Member", "Matchmaker"))
    intro = _get_intro_or_404(intro_id)
    body = get_json_body()
    scheduled_by = require_str(body, "scheduled_by_member_id")
    start_at = require_str(body, "start_at")
    end_at = require_str(body, "end_at")
    start_dt = parse_iso(start_at)
    end_dt = parse_iso(end_at)
    now = clock.now()
    if start_dt < now:
        raise errors.invalid_request("Date start_at must be >= clock now.")
    if end_dt <= start_dt:
        raise errors.invalid_request("Date end_at must be > start_at.")

    # ownership: a Member may only schedule for themselves and must be a party
    if principal.role == "Member" and principal.user_id != scheduled_by:
        raise errors.forbidden()

    # (5) introduction must be MUTUAL to schedule a date
    if intro["status"] != "MUTUAL":
        raise errors.conflict("ERR_INVALID_INTRODUCTION_STATE")

    # (6) scheduler must be a party
    if scheduled_by not in (intro["member_a_id"], intro["member_b_id"]):
        raise errors.unprocessable("ERR_NOT_INTRODUCTION_PARTY")

    # (8) calendar overlap
    if date_overlaps_existing(scheduled_by, start_dt, end_dt):
        raise errors.conflict("ERR_DATE_OVERLAP")

    did = new_id()
    date_event = {
        "id": did,
        "introduction_id": intro_id,
        "scheduled_by_member_id": scheduled_by,
        "start_at": iso_now_ms(start_dt),
        "end_at": iso_now_ms(end_dt),
        "outcome": "NONE",
        "status": "SCHEDULED",
    }
    stamp_create(date_event)
    db.date_events[did] = date_event
    return success_object(serialize_date_event(date_event), 201)


@bp.route("/introductions/<intro_id>/date-events", methods=["GET"])
def list_dates(intro_id):
    principal = authenticate()
    require_roles(principal, ALL_ROLES)
    intro = _get_intro_or_404(intro_id)
    if principal.role == "Member" and principal.user_id not in (intro["member_a_id"], intro["member_b_id"]):
        raise errors.forbidden()
    limit, offset = parse_pagination()
    records = [d for d in db.date_events.values() if d["introduction_id"] == intro_id]
    records = sort_by_created(records)
    page, total = paginate(records, limit, offset)
    return success_array([serialize_date_event(d) for d in page], limit, offset, total)


@bp.route("/date-events/<date_id>", methods=["GET"])
def get_date(date_id):
    principal = authenticate()
    require_roles(principal, ALL_ROLES)
    d = _get_date_or_404(date_id)
    if principal.role == "Member":
        intro = db.introductions.get(d["introduction_id"])
        parties = (intro["member_a_id"], intro["member_b_id"]) if intro else ()
        if principal.user_id not in parties:
            raise errors.forbidden()
    return success_object(serialize_date_event(d))


@bp.route("/date-events/<date_id>/outcome", methods=["POST"])
def record_outcome(date_id):
    principal = authenticate()
    require_roles(principal, ("Matchmaker",))
    d = _get_date_or_404(date_id)
    body = get_json_body()
    outcome = require_enum(body, "outcome", ("COMPLETED", "NO_SHOW"))
    if d["status"] != "SCHEDULED":
        raise errors.conflict("ERR_DATE_NOT_SCHEDULED")
    now = clock.now()
    if now < parse_iso(d["start_at"]):
        raise errors.conflict("ERR_DATE_NOT_STARTED")
    d["outcome"] = outcome
    d["status"] = outcome
    touch(d)
    return success_object(serialize_date_event(d))


@bp.route("/date-events/<date_id>/cancel", methods=["POST"])
def cancel_date(date_id):
    principal = authenticate()
    require_roles(principal, ("Member", "Matchmaker"))
    d = _get_date_or_404(date_id)
    if principal.role == "Member":
        intro = db.introductions.get(d["introduction_id"])
        parties = (intro["member_a_id"], intro["member_b_id"]) if intro else ()
        if principal.user_id not in parties:
            raise errors.forbidden()
    if d["status"] != "SCHEDULED":
        raise errors.conflict("ERR_DATE_NOT_SCHEDULED")
    d["outcome"] = "CANCELLED"
    d["status"] = "CANCELLED"
    touch(d)
    return success_object(serialize_date_event(d))
