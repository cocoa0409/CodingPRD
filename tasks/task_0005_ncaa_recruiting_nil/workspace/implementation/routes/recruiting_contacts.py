"""RecruitingContact endpoints."""

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_DEAD_PERIOD_CONTACT,
    ERR_OUTSIDE_RECRUITING_WINDOW,
    ERR_QUIET_PERIOD_VIOLATION,
    invalid_request,
    not_found,
)
from helpers import (
    get_body,
    paginate,
    parse_pagination,
    require_enum,
    require_field,
    sort_created_at_asc,
)
from middleware import require_roles
from response import ok_array, ok_object

bp = Blueprint("recruiting_contacts", __name__)


CHANNELS = {"IN_PERSON", "PHONE", "DM", "EMAIL"}


def _find_period_at(program_id: str, ts_dt):
    """Find the Period (if any) whose [starts_at, ends_at) contains ts_dt."""
    for p in db.periods.values():
        if p["program_id"] != program_id:
            continue
        s = db.parse_iso(p["starts_at"])
        e = db.parse_iso(p["ends_at"])
        if s <= ts_dt < e:
            return p
    return None


@bp.post("/ncaa/recruiting-contacts")
def create_contact():
    require_roles("Coach")
    body = get_body()
    program_id = require_field(body, "program_id", str)
    athlete_id = require_field(body, "student_athlete_id", str)
    coach_user_id = require_field(body, "coach_user_id", str)
    contact_at = require_field(body, "contact_at", str)
    channel = require_field(body, "channel", str)
    require_enum(channel, "channel", CHANNELS)
    # Body FK resolution
    program = db.programs.get(program_id)
    if program is None:
        raise not_found("Program not found.")
    athlete = db.student_athletes.get(athlete_id)
    if athlete is None:
        raise not_found("StudentAthlete not found.")
    # Parse contact_at
    try:
        ts_dt = db.parse_iso(contact_at)
    except ValueError as e:
        raise invalid_request(str(e))
    # Calendar checks in fixed order: DEAD -> QUIET-wrong-channel -> gap
    period = _find_period_at(program_id, ts_dt)
    if period is not None and period["period_type"] == "DEAD":
        raise APIError(
            ERR_DEAD_PERIOD_CONTACT,
            "Contact prohibited during a DEAD period.",
            422,
        )
    if period is not None and period["period_type"] == "QUIET" and channel != "IN_PERSON":
        raise APIError(
            ERR_QUIET_PERIOD_VIOLATION,
            "Only IN_PERSON contact is permitted during a QUIET period.",
            422,
        )
    if period is None:
        raise APIError(
            ERR_OUTSIDE_RECRUITING_WINDOW,
            "contact_at falls outside any defined recruiting Period.",
            422,
        )
    row = {
        "id": db.new_id(),
        "program_id": program_id,
        "student_athlete_id": athlete_id,
        "coach_user_id": coach_user_id,
        "contact_at": contact_at,
        "channel": channel,
        "period_type_at_contact": period["period_type"],
    }
    db.stamp_create(row)
    db.recruiting_contacts[row["id"]] = row
    return ok_object(row, 201)


@bp.get("/ncaa/recruiting-contacts/<contact_id>")
def get_contact(contact_id):
    require_roles("ComplianceOfficer", "Coach")
    row = db.recruiting_contacts.get(contact_id)
    if row is None:
        raise not_found("RecruitingContact not found.")
    return ok_object(row)


@bp.get("/ncaa/recruiting-contacts")
def list_contacts():
    require_roles("ComplianceOfficer", "Coach")
    limit, offset = parse_pagination()
    rows = list(db.recruiting_contacts.values())
    program_id = request.args.get("program_id")
    athlete_id = request.args.get("student_athlete_id")
    coach_user_id = request.args.get("coach_user_id")
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if athlete_id is not None:
        rows = [r for r in rows if r["student_athlete_id"] == athlete_id]
    if coach_user_id is not None:
        rows = [r for r in rows if r["coach_user_id"] == coach_user_id]
    rows = sort_created_at_asc(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return ok_array(page, limit=limit, offset=offset,
                    total_count=total, has_more=has_more)
