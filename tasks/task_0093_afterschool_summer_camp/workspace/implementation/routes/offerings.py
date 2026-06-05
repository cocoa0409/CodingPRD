"""WeeklyOffering and WeatherEvent routes (PRD §3.2, §3.5)."""
from __future__ import annotations

from flask import Blueprint, request

from db import db, now_iso
from errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_STALE_OFFERING_VERSION,
    ERR_ALTERNATE_AGE_MISMATCH,
    ERR_ALTERNATE_OVER_CAPACITY,
)
from middleware import require_roles, ROLE_GUARDIAN, ROLE_DIRECTOR, ROLE_BILLING
from response import ok_object, ok_array, paginate_params, slice_page
from services.common import (
    make_record,
    serialize,
    serialize_list,
    sort_by_created,
    touch,
    audit,
    get_body,
    require_str,
    require_int,
)
from services.calculations import (
    reconcile_offering_counts,
    compute_child_age,
    RAIN_OVERFLOW_TOLERANCE,
)
from services.lookups import get_session, get_weekly_offering

bp = Blueprint("offerings", __name__)


@bp.post("/weekly-offerings")
def create_weekly_offering():
    require_roles(ROLE_DIRECTOR)
    body = get_body()
    session_id = require_str(body, "session_id")
    week_start = require_str(body, "week_start")
    get_session(session_id)

    rain_alt = None
    if "rain_alternate_offering_id" in body and body["rain_alternate_offering_id"] is not None:
        rain_alt = require_str(body, "rain_alternate_offering_id")
        get_weekly_offering(rain_alt)  # existence check (priority 3)

    rec = make_record(
        {
            "session_id": session_id,
            "week_start": week_start,
            "enrolled_count": 0,
            "waitlist_count": 0,
            "capacity_state": "AVAILABLE",
            "weather_state": "NORMAL",
            "rain_alternate_offering_id": rain_alt,
        }
    )
    db.weekly_offerings[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/weekly-offerings/<wid>")
def fetch_weekly_offering(wid):
    require_roles(ROLE_GUARDIAN, ROLE_DIRECTOR, ROLE_BILLING)
    rec = get_weekly_offering(wid)
    return ok_object(serialize(rec), 200)


@bp.get("/weekly-offerings/<wid>/rain-dependents")
def list_rain_dependents(wid):
    require_roles(ROLE_GUARDIAN, ROLE_DIRECTOR)
    get_weekly_offering(wid)
    limit, offset = paginate_params(request.args)
    items = [
        w for w in db.weekly_offerings.values() if w.get("rain_alternate_offering_id") == wid
    ]
    items = sort_by_created(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.get("/weekly-offerings/<wid>/enrollments")
def list_offering_enrollments(wid):
    require_roles(ROLE_GUARDIAN, ROLE_DIRECTOR, ROLE_BILLING)
    get_weekly_offering(wid)
    limit, offset = paginate_params(request.args)
    status = request.args.get("status")
    items = [e for e in db.enrollments.values() if e["weekly_offering_id"] == wid]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items = sort_by_created(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.get("/weekly-offerings/<wid>/weather-events")
def list_offering_weather_events(wid):
    require_roles(ROLE_DIRECTOR, ROLE_BILLING)
    get_weekly_offering(wid)
    limit, offset = paginate_params(request.args)
    items = [we for we in db.weather_events.values() if we["weekly_offering_id"] == wid]
    items = sort_by_created(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.patch("/weekly-offerings/<wid>")
def configure_rain_alternate(wid):
    require_roles(ROLE_DIRECTOR)
    offering = get_weekly_offering(wid)
    body = get_body()
    rain_alt = require_str(body, "rain_alternate_offering_id")
    expected_version = require_int(body, "expected_weekly_offering_version")
    get_weekly_offering(rain_alt)  # existence of the alternate
    if expected_version != offering["version"]:
        raise APIError(ERR_STALE_OFFERING_VERSION, 412, "Stale weekly offering version")
    offering["rain_alternate_offering_id"] = rain_alt
    touch(offering)
    return ok_object(serialize(offering), 200)


@bp.post("/weekly-offerings/<wid>/clear-rain")
def clear_rain(wid):
    caller = require_roles(ROLE_DIRECTOR)
    offering = get_weekly_offering(wid)
    if offering["weather_state"] != "RAIN_ACTIVATED":
        raise APIError(ERR_INVALID_STATE, 409, "Offering is not RAIN_ACTIVATED")
    offering["weather_state"] = "NORMAL"
    touch(offering)
    audit("WeeklyOffering", offering["id"], "RAIN_CLEARED", caller.role)
    return ok_object(serialize(offering), 200)


# ---------------------------------------------------------------------------
# WeatherEvent — declare rain, relocate confirmed children (PRD §3.5)
# ---------------------------------------------------------------------------
@bp.post("/weather-events")
def declare_rain():
    caller = require_roles(ROLE_DIRECTOR)
    body = get_body()
    wid = require_str(body, "weekly_offering_id")
    offering = get_weekly_offering(wid)

    # state precondition: must be NORMAL
    if offering["weather_state"] != "NORMAL":
        raise APIError(ERR_INVALID_STATE, 409, "Offering weather is not NORMAL")
    # must have a configured alternate
    alt_id = offering.get("rain_alternate_offering_id")
    if not alt_id:
        raise APIError(ERR_INVALID_STATE, 409, "No rain alternate configured")
    alternate = get_weekly_offering(alt_id)
    # parent session must be OPEN
    session = db.sessions[offering["session_id"]]
    if session["status"] != "OPEN":
        raise APIError(ERR_INVALID_STATE, 409, "Parent session is not OPEN")

    alt_session = db.sessions[alternate["session_id"]]

    # confirmed children to relocate, in created_at ASC order
    confirmed = [
        e
        for e in db.enrollments.values()
        if e["weekly_offering_id"] == wid and e["status"] == "CONFIRMED"
    ]
    confirmed = sort_by_created(confirmed)

    # guard rail 1: every relocating child's age must fit the alternate's group
    for e in confirmed:
        child = db.children[e["child_id"]]
        age = compute_child_age(child, alt_session)
        if not (alt_session["age_group_min"] <= age <= alt_session["age_group_max"]):
            raise APIError(
                ERR_ALTERNATE_AGE_MISMATCH, 422, "A relocating child does not fit the alternate's age group"
            )

    # weekly_capacity lives on the Session, not the WeeklyOffering.
    alt_capacity = alt_session["weekly_capacity"]

    # guard rail 2: relocate count may exceed alternate capacity by at most 1
    relocate_count = len(confirmed)
    if relocate_count > alt_capacity + RAIN_OVERFLOW_TOLERANCE:
        raise APIError(
            ERR_ALTERNATE_OVER_CAPACITY, 409, "Relocation exceeds the alternate's overflow tolerance"
        )

    # passes -> relocate. Children that fit alternate capacity remain CONFIRMED;
    # overflow lands WAITLISTED on the alternate but is still relocated.
    existing_alt_confirmed = sum(
        1
        for e in db.enrollments.values()
        if e["weekly_offering_id"] == alt_id and e["status"] == "CONFIRMED"
    )
    seats_left = max(0, alt_capacity - existing_alt_confirmed)

    for e in confirmed:
        e["weekly_offering_id"] = alt_id
        if seats_left > 0:
            e["status"] = "CONFIRMED"
            seats_left -= 1
        else:
            e["status"] = "WAITLISTED"
        touch(e)

    offering["weather_state"] = "RAIN_ACTIVATED"
    reconcile_offering_counts(offering)
    reconcile_offering_counts(alternate)

    event = make_record(
        {
            "weekly_offering_id": wid,
            "declared_at": now_iso(),
            "moved_enrollment_count": relocate_count,
        },
        versioned=False,
    )
    db.weather_events[event["id"]] = event
    audit("WeeklyOffering", offering["id"], "RAIN_ACTIVATED", caller.role)
    return ok_object(serialize(event), 201)
