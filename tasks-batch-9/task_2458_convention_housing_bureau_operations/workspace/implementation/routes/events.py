"""Event registration and reads (PRD §3.1)."""

from flask import Blueprint

import calc
import serializers as ser
import validators as V
from auth import authenticate
from envelope import created, ok
from errors import fail
from store import ALL_ROLES, STORE, base_record, days_between, parse_iso_date

bp = Blueprint("events", __name__, url_prefix="/housing")


@bp.post("/events")
def create_event():
    authenticate(["BureauCoordinator"])
    body = V.json_body()

    name = V.field_str(body, "name", min_len=1, max_len=160)
    code = V.field_str(body, "code", min_len=3, max_len=16)
    if code != code.upper():
        fail("ERR_INVALID_REQUEST", "code must be uppercase")
    event_start_date = V.field_date(body, "event_start_date")
    event_end_date = V.field_date(body, "event_end_date")
    if parse_iso_date(event_end_date) <= parse_iso_date(event_start_date):
        fail("ERR_INVALID_REQUEST", "event_end_date must be strictly after event_start_date")
    cutoff_date = V.field_date(body, "cutoff_date")
    attrition_deadline_date = V.field_date(body, "attrition_deadline_date")
    standard_commission_pct = V.field_number(
        body, "standard_commission_pct", exclusive_minimum=0, maximum=0.25
    )
    standard_rebate = V.field_int(body, "standard_rebate_per_room_night_cents", minimum=0)

    for existing in STORE.events.values():
        if existing["code"] == code:
            fail("ERR_EVENT_CODE_DUPLICATE", "event code %s is already registered" % code)

    record = base_record()
    record.update(
        {
            "name": name,
            "code": code,
            "event_start_date": event_start_date,
            "event_end_date": event_end_date,
            "cutoff_date": cutoff_date,
            "attrition_deadline_date": attrition_deadline_date,
            "standard_commission_pct": standard_commission_pct,
            "standard_rebate_per_room_night_cents": standard_rebate,
            "night_count": days_between(event_start_date, event_end_date),
            "housing_posture": "PLANNING",
            "total_contracted_room_nights": 0,
            "total_confirmed_room_nights": 0,
            "commission_collected_cents": 0,
        }
    )
    STORE.events[record["id"]] = record
    return created(ser.event_out(record))


@bp.get("/events/<event_id>")
def read_event(event_id):
    authenticate(ALL_ROLES)
    event = V.get_event(event_id)
    return ok(ser.event_out(event))
