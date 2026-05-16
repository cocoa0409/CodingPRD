"""/recruiting-calendars endpoints."""

from datetime import timedelta
from flask import Blueprint, request

from core.auth import require_roles
from core.clock import parse_iso
from core.envelope import success_object, success_array
from core.errors import raise_error
from core.models import make_entity, serialize, serialize_list
from core.store import STORE, lock
from core.validation import (
    require_body,
    require_field,
    require_enum,
    require_iso_datetime,
    parse_pagination,
    parse_iso_query,
)


bp = Blueprint("recruiting_calendars", __name__)


VALID_PERIOD_TYPES = {"QUIET", "CONTACT", "DEAD", "EVALUATION"}


@bp.route("/recruiting-calendars", methods=["POST"])
@require_roles("ComplianceOfficer")
def create_calendar():
    body = require_body(request)
    program_id = require_field(body, "program_id", kind="string")
    period_type = require_enum(body, "period_type", VALID_PERIOD_TYPES)
    start_dt = require_iso_datetime(body, "start_date")
    end_dt = require_iso_datetime(body, "end_date")
    note = body.get("note", "")
    if note is not None and not isinstance(note, str):
        raise_error("ERR_VALIDATION_FAILED", "note must be a string")

    with lock():
        if program_id not in STORE.programs:
            raise_error("ERR_REFERENCE_NOT_FOUND", "Program not found")

        # Calendar window shape: start < end and duration >= 1 day
        if start_dt >= end_dt:
            raise_error("ERR_CALENDAR_WINDOW_INVALID", "start_date must be strictly before end_date")
        if end_dt - start_dt < timedelta(days=1):
            raise_error("ERR_CALENDAR_WINDOW_INVALID", "Window must be at least one day long")

        from core.clock import iso_format
        cal = make_entity("RecruitingCalendar", {
            "program_id": program_id,
            "period_type": period_type,
            "start_date": iso_format(start_dt),
            "end_date": iso_format(end_dt),
            "note": note or "",
        })
        STORE.recruiting_calendars[cal["id"]] = cal
        return success_object(serialize(cal), status=201)


@bp.route("/recruiting-calendars/<calendar_id>", methods=["GET"])
@require_roles("ComplianceOfficer", "Coach", "Auditor")
def get_calendar(calendar_id):
    with lock():
        c = STORE.recruiting_calendars.get(calendar_id)
        if not c:
            raise_error("ERR_NOT_FOUND", "RecruitingCalendar not found")
        return success_object(serialize(c))


@bp.route("/recruiting-calendars", methods=["GET"])
@require_roles("ComplianceOfficer", "Coach", "Auditor")
def list_calendars():
    limit, offset = parse_pagination(request)
    program_id = request.args.get("program_id")
    period_type = request.args.get("period_type")
    contains_date_raw = request.args.get("contains_date")
    contains_date = None
    if contains_date_raw is not None:
        contains_date = parse_iso_query(contains_date_raw, "contains_date")

    with lock():
        items = list(STORE.recruiting_calendars.values())
        if program_id:
            items = [c for c in items if c.get("program_id") == program_id]
        if period_type:
            items = [c for c in items if c.get("period_type") == period_type]
        if contains_date is not None:
            def covers(c):
                s = parse_iso(c["start_date"])
                e = parse_iso(c["end_date"])
                return s <= contains_date < e
            items = [c for c in items if covers(c)]
        items.sort(key=lambda c: (c["created_at"], c["_seq"]))
        total = len(items)
        page = items[offset:offset + limit]
        return success_array(serialize_list(page), limit, offset, total)
