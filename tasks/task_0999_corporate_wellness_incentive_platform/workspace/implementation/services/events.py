"""ActivityEvent endpoints (PRD §3.5): idempotent device/app sync ingest,
points conversion with daily cap, challenge-progress cascade."""
from datetime import datetime, time, timezone

from flask import Blueprint

from db import DB
from errors import ApiError, invalid
from middleware import require_roles
from response import success
from services import serializers
from services.cascade import (
    DAILY_CAP, complete_participation, make_ledger_entry,
    participation_progress, recompute_balances,
)
from services.common import (
    check_employee_scope, get_enrollment_or_404, get_event_or_404,
    list_response, parse_body, require_fields, stamp_new, touch,
)
from clock import CLOCK, iso_from_dt

bp = Blueprint("events", __name__)

_ACTIVITY_TYPES = {"STEPS", "MINUTES", "VISITS"}


def _raw_points(activity_type, quantity):
    if activity_type == "STEPS":
        return quantity // 1000
    if activity_type == "MINUTES":
        return quantity // 30
    return quantity * 10  # VISITS


@bp.post("/wellness/activity-events")
@require_roles("Employee")
def ingest_event():
    body = parse_body()
    vals = require_fields(body, [
        ("enrollment_id", "string", True),
        ("device_source", "string", True),
        ("external_event_id", "string", True),
        ("activity_type", "enum", True, _ACTIVITY_TYPES),
        ("quantity", "int", True),
        ("occurred_at", "datetime", True),
    ])
    enr = get_enrollment_or_404(vals["enrollment_id"])
    check_employee_scope(enr)
    if enr["participation_status"] != "ACTIVE":
        raise ApiError(
            "ERR_ENROLLMENT_NOT_ACTIVE",
            "Activity ingestion requires an ACTIVE enrollment",
        )
    if vals["quantity"] <= 0:
        raise invalid("quantity must be > 0")
    occurred = vals["occurred_at"]

    # idempotency on (enrollment_id, device_source, external_event_id) —
    # uniqueness family (stage 8) precedes temporal window checks (stage 9)
    for existing in DB.events.values():
        if (
            existing["enrollment_id"] == enr["id"]
            and existing["device_source"] == vals["device_source"]
            and existing["external_event_id"] == vals["external_event_id"]
        ):
            same_payload = (
                existing["activity_type"] == vals["activity_type"]
                and existing["quantity"] == vals["quantity"]
                and existing["_occurred"] == occurred
            )
            if same_payload:
                # identical replay: 200 with the existing event, no side effects
                return success(serializers.activity_event(existing), status=200)
            raise ApiError(
                "ERR_DUPLICATE_EVENT",
                "Idempotency key reused with a different payload",
            )

    # temporal window: inside the plan year and not in the future
    program = DB.programs[enr["program_id"]]
    py_start = datetime.combine(program["_pys"], time.min, tzinfo=timezone.utc)
    py_end = datetime.combine(program["_pye"], time.min, tzinfo=timezone.utc)
    if occurred < py_start or occurred >= py_end or occurred > CLOCK.now():
        raise ApiError(
            "ERR_EVENT_OUTSIDE_WINDOW",
            "occurred_at must be inside the program plan year and not in the future",
        )

    # points conversion with the daily cap (activity_points_conversion)
    day_key = occurred.date()
    day_total = sum(
        ev["points_granted"]
        for ev in DB.events.values()
        if ev["enrollment_id"] == enr["id"] and ev["_occurred"].date() == day_key
    )
    headroom = max(0, DAILY_CAP - day_total)
    granted = min(_raw_points(vals["activity_type"], vals["quantity"]), headroom)

    rec = stamp_new(
        {
            "enrollment_id": enr["id"],
            "device_source": vals["device_source"],
            "external_event_id": vals["external_event_id"],
            "activity_type": vals["activity_type"],
            "quantity": vals["quantity"],
            "occurred_at": iso_from_dt(occurred),
            "_occurred": occurred,
            "points_granted": granted,
        },
        common=False,  # ActivityEvent carries only id + created_at (PRD §2.4)
    )
    DB.events[rec["id"]] = rec

    # ledger + balances
    make_ledger_entry(enr, "EARNED", granted, source_event_id=rec["id"],
                      status="PROVISIONAL")
    recompute_balances(enr)

    # challenge cascade: recompute JOINED participations matching activity_type
    for p in sorted(
        (p for p in DB.participations.values()
         if p["enrollment_id"] == enr["id"] and p["status"] == "JOINED"),
        key=lambda p: p["created_at"],
    ):
        challenge = DB.challenges[p["challenge_id"]]
        if challenge["activity_type"] != vals["activity_type"]:
            continue
        new_progress = participation_progress(p, challenge)
        if new_progress != p["progress_quantity"]:
            p["progress_quantity"] = new_progress
            touch(p)
        if p["progress_quantity"] >= challenge["goal_quantity"]:
            complete_participation(p, challenge)

    return success(serializers.activity_event(rec), status=201)


@bp.get("/wellness/activity-events/<eid>")
@require_roles("PlatformAdmin", "BenefitsAdmin", "Employee")
def get_event(eid):
    ev = get_event_or_404(eid)
    check_employee_scope(DB.enrollments[ev["enrollment_id"]])
    return success(serializers.activity_event(ev))


@bp.get("/wellness/activity-events/<eid>/points-ledger-entries")
@require_roles("PlatformAdmin", "BenefitsAdmin")
def list_event_ledger(eid):
    get_event_or_404(eid)
    items = [le for le in DB.ledger.values() if le["source_activity_event_id"] == eid]
    return list_response(items, serializers.ledger_entry)
