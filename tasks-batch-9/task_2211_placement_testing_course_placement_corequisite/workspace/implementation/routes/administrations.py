"""Test administrations: scheduling geometry and the session status machine."""

from datetime import timedelta

from flask import Blueprint

from constants import (
    ADMIN_STATUSES,
    ATTEMPT_STATES,
    MAX_SESSION_MINUTES,
    PROCTOR_DAILY_MINUTES_CAP,
    ROOM_TURNAROUND_MINUTES,
    RULE_SUBJECTS,
)
from db import base_row, db, touch
from errors import fail
from middleware import authenticate
from response import created, ok
from routes.common import eq, filter_rows, find, listing
from services import cascades, serialize
from validators import Field, parse_body, parse_query

bp = Blueprint("administrations", __name__)

READERS = ("AssessmentStaff", "Proctor", "AssessmentDirector", "Student")
LIVE_STATUSES = ("SCHEDULED", "OPEN", "CLOSED")

CREATE_SPEC = {
    "room_code": Field("str", required=True),
    "subject_area": Field("enum", required=True, values=RULE_SUBJECTS),
    "proctor_user_id": Field("str", required=True),
    "starts_at": Field("datetime", required=True),
    "ends_at": Field("datetime", required=True),
    "seat_capacity": Field("int", required=True, minimum=1, maximum=200),
}

LIST_SPEC = {
    "room_code": Field("str"),
    "subject_area": Field("enum", values=RULE_SUBJECTS),
    "status": Field("enum", values=ADMIN_STATUSES),
    "proctor_user_id": Field("str"),
    "starts_at_from": Field("datetime"),
    "starts_at_to": Field("datetime"),
}

STATUS_SPEC = {"target_status": Field("enum", required=True, values=ADMIN_STATUSES)}
ATTEMPT_LIST_SPEC = {"state": Field("enum", values=ATTEMPT_STATES)}


def _daily_minutes(starts_at, ends_at, buckets):
    """Add a sitting's minutes to each UTC calendar day it touches."""
    day = starts_at.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < ends_at:
        day_end = day + timedelta(days=1)
        lo = max(starts_at, day)
        hi = min(ends_at, day_end)
        if hi > lo:
            key = day.date()
            buckets[key] = buckets.get(key, 0) + int((hi - lo).total_seconds() // 60)
        day = day_end
    return buckets


@bp.post("/test-administrations")
def create_administration():
    authenticate(("AssessmentStaff",))
    body = parse_body(CREATE_SPEC)

    starts_at = body["starts_at"]
    ends_at = body["ends_at"]
    if not (ends_at > starts_at):
        fail("ERR_INVALID_REQUEST", "ends_at must be strictly after starts_at")
    if (ends_at - starts_at).total_seconds() / 60.0 > MAX_SESSION_MINUTES:
        fail("ERR_INVALID_REQUEST", "a sitting may not run longer than eight hours")

    buffer = timedelta(minutes=ROOM_TURNAROUND_MINUTES)
    for other in db.administrations.values():
        if other["room_code"] != body["room_code"] or other["status"] not in LIVE_STATUSES:
            continue
        if other["starts_at"] < ends_at + buffer and starts_at < other["ends_at"] + buffer:
            fail("ERR_ROOM_TIME_CONFLICT", "the room needs thirty minutes of turnaround")

    buckets = {}
    for other in db.administrations.values():
        if other["proctor_user_id"] != body["proctor_user_id"]:
            continue
        if other["status"] not in LIVE_STATUSES:
            continue
        _daily_minutes(other["starts_at"], other["ends_at"], buckets)
    _daily_minutes(starts_at, ends_at, buckets)
    for minutes in buckets.values():
        if minutes > PROCTOR_DAILY_MINUTES_CAP:
            fail("ERR_PROCTOR_DAILY_CAP_EXCEEDED", "the proctor's daily minutes exceed eight hours")

    row = base_row()
    row.update({
        "room_code": body["room_code"],
        "subject_area": body["subject_area"],
        "proctor_user_id": body["proctor_user_id"],
        "starts_at": starts_at,
        "ends_at": ends_at,
        "seat_capacity": body["seat_capacity"],
        "status": "SCHEDULED",
    })
    db.administrations[row["id"]] = row
    return created(serialize.administration(row))


@bp.get("/test-administrations/<administration_id>")
def get_administration(administration_id):
    authenticate(READERS)
    parse_query({}, paginated=False)
    row = find("administrations", administration_id)
    return ok(serialize.administration(row))


@bp.get("/test-administrations")
def list_administrations():
    authenticate(READERS)
    query = parse_query(LIST_SPEC)
    rows = filter_rows(list(db.administrations.values()), query, {
        "room_code": eq("room_code"),
        "subject_area": eq("subject_area"),
        "status": eq("status"),
        "proctor_user_id": eq("proctor_user_id"),
        "starts_at_from": lambda r, v: r["starts_at"] >= v,
        "starts_at_to": lambda r, v: r["starts_at"] <= v,
    })
    return listing(rows, query, serialize.administration)


@bp.post("/test-administrations/<administration_id>/status")
def set_status(administration_id):
    user_id, role = authenticate(("Proctor", "AssessmentStaff", "AssessmentDirector"))
    body = parse_body(STATUS_SPEC)
    row = find("administrations", administration_id)

    target = body["target_status"]
    current = row["status"]
    allowed = {
        "OPEN": ("SCHEDULED",),
        "CLOSED": ("OPEN",),
        "CANCELLED": ("SCHEDULED", "OPEN"),
    }
    if target not in allowed or current not in allowed[target]:
        fail("ERR_INVALID_STATE", "%s -> %s is not a declared transition" % (current, target))

    if role == "Proctor" and user_id != row["proctor_user_id"]:
        fail("ERR_NOT_ASSIGNED_PROCTOR", "X-User-ID is not the session's assigned proctor")

    if target == "OPEN" and not (db.clock < row["ends_at"]):
        fail("ERR_ADMINISTRATION_WINDOW_PASSED", "the sitting has already passed")

    row["status"] = target
    touch(row)
    if target == "CLOSED":
        cascades.close_administration(row)
    elif target == "CANCELLED":
        cascades.cancel_administration(row)
    return ok(serialize.administration(row))


@bp.get("/test-administrations/<administration_id>/attempts")
def list_administration_attempts(administration_id):
    authenticate(("AssessmentStaff", "Proctor", "AssessmentDirector"))
    query = parse_query(ATTEMPT_LIST_SPEC)
    row = find("administrations", administration_id)
    rows = [a for a in db.attempts.values() if a["administration_id"] == row["id"]]
    rows = filter_rows(rows, query, {"state": eq("state")})
    return listing(rows, query, serialize.attempt)
