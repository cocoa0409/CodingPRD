"""Show-floor labor under union jurisdiction (PRD 3.6)."""

from flask import Blueprint

import calc
import lookups
import validate
from db import db
from errors import err
from middleware import body, endpoint, filter_rows, touch
from response import entity_response
from routes.common import SERVICE_CATEGORIES, body_fk, listing, require_posture
from services import engine
from util import parse_date

bp = Blueprint("labor", __name__)


@bp.post("/bookings/<booking_id>/labor-calls")
@endpoint("EventServicesManager")
def create_labor_call(booking_id):
    booking = lookups.fetch("booking", booking_id)
    payload = body()

    # ladder step 5 then step 7
    jurisdiction = body_fk(payload, "jurisdiction_id", "jurisdiction")
    work_category = validate.req_enum(payload, "work_category", SERVICE_CATEGORIES)
    work_date = validate.req_date(payload, "work_date")
    start_hour = validate.req_number(payload, "scheduled_start_hour", minimum=0, exclusive_max=24)
    end_hour = validate.req_number(payload, "scheduled_end_hour", maximum=24)
    if end_hour <= start_hour:
        raise err(
            "ERR_INVALID_REQUEST",
            "Field 'scheduled_end_hour' must be greater than 'scheduled_start_hour'.",
        )
    crew_size = validate.req_int(payload, "crew_size", minimum=1)

    # ladder step 10, then the union gates of step 14
    require_posture(booking)
    if jurisdiction["lockout_active"]:
        raise err("ERR_UNION_LOCKOUT")
    if jurisdiction["covered_category"] != work_category:
        raise err("ERR_UNION_JURISDICTION_MISMATCH")

    # ladder step 15: the work day must sit inside the event span
    if not (
        parse_date(booking["move_in_start_date"])
        <= work_date
        <= parse_date(booking["move_out_end_date"])
    ):
        raise err("ERR_WORK_DATE_OUTSIDE_EVENT")

    # ladder step 16: the local's daily crew-hour capacity
    fields = {
        "booking_id": booking["id"],
        "jurisdiction_id": jurisdiction["id"],
        "work_category": work_category,
        "work_date": work_date.isoformat(),
        "scheduled_start_hour": start_hour,
        "scheduled_end_hour": end_hour,
        "crew_size": crew_size,
        "actual_start_hour": None,
        "actual_end_hour": None,
        "status": "SCHEDULED",
        "actual_charge_cents": None,
    }
    billed_hours = calc.union_crew_hours_committed(fields, jurisdiction, actualized=False)
    already = engine.crew_hours_on_date(jurisdiction["id"], work_date.isoformat())
    if calc.one_decimal(already + billed_hours) > jurisdiction["max_crew_hours_per_day"]:
        raise err("ERR_UNION_CREW_OVERCOMMITTED")

    fields["billed_hours"] = billed_hours
    fields["estimated_charge_cents"] = calc.union_labor_charge_estimate(fields, jurisdiction)
    call = db.insert("labor_call", fields)
    engine.recompute_committed_crew_hours(jurisdiction)
    return entity_response(call, 201)


@bp.get("/labor-calls")
@endpoint("VenueAdmin", "EventServicesManager", "SettlementAnalyst")
def list_labor_calls():
    rows = filter_rows(
        "labor_call",
        {"booking_id": "booking_id", "jurisdiction_id": "jurisdiction_id", "status": "status"},
    )
    return listing(rows)


@bp.get("/labor-calls/<call_id>")
@endpoint("VenueAdmin", "EventServicesManager", "SettlementAnalyst")
def read_labor_call(call_id):
    return entity_response(lookups.fetch("labor_call", call_id))


@bp.post("/labor-calls/<call_id>/dispatch")
@endpoint("EventServicesManager")
def dispatch_labor_call(call_id):
    call = lookups.fetch("labor_call", call_id)
    if call["status"] != "SCHEDULED":
        raise err("ERR_LABOR_CALL_STATE_INVALID")
    booking = db.bookings.get(call["booking_id"])
    if booking is None or booking["status"] != "IN_HOUSE":
        raise err("ERR_BOOKING_STATE_INVALID")
    jurisdiction = db.jurisdictions.get(call["jurisdiction_id"])
    if jurisdiction is not None and jurisdiction["lockout_active"]:
        raise err("ERR_UNION_LOCKOUT")

    call["status"] = "DISPATCHED"
    touch(call)
    return entity_response(call)


@bp.post("/labor-calls/<call_id>/actualize")
@endpoint("EventServicesManager")
def actualize_labor_call(call_id):
    call = lookups.fetch("labor_call", call_id)
    payload = body()
    actual_start = validate.req_number(payload, "actual_start_hour")
    actual_end = validate.req_number(payload, "actual_end_hour")
    if actual_end <= actual_start:
        raise err(
            "ERR_INVALID_REQUEST",
            "Field 'actual_end_hour' must be greater than 'actual_start_hour'.",
        )

    if call["status"] != "DISPATCHED":
        raise err("ERR_LABOR_CALL_STATE_INVALID")
    jurisdiction = db.jurisdictions.get(call["jurisdiction_id"])

    probe = dict(call)
    probe["actual_start_hour"] = actual_start
    probe["actual_end_hour"] = actual_end
    billed_hours = calc.union_crew_hours_committed(probe, jurisdiction, actualized=True)
    already = engine.crew_hours_on_date(
        call["jurisdiction_id"], call["work_date"], exclude_call_id=call["id"]
    )
    if calc.one_decimal(already + billed_hours) > jurisdiction["max_crew_hours_per_day"]:
        raise err("ERR_UNION_CREW_OVERCOMMITTED")

    call["actual_start_hour"] = actual_start
    call["actual_end_hour"] = actual_end
    call["status"] = "ACTUALIZED"
    call["billed_hours"] = billed_hours
    call["actual_charge_cents"] = calc.union_labor_charge_actual(call, jurisdiction)
    touch(call)
    engine.recompute_committed_crew_hours(jurisdiction)
    return entity_response(call)


@bp.post("/labor-calls/<call_id>/cancel")
@endpoint("EventServicesManager")
def cancel_labor_call(call_id):
    call = lookups.fetch("labor_call", call_id)
    if call["status"] not in ("SCHEDULED", "DISPATCHED"):
        raise err("ERR_LABOR_CALL_STATE_INVALID")

    call["status"] = "CANCELLED"
    call["billed_hours"] = 0
    touch(call)
    jurisdiction = db.jurisdictions.get(call["jurisdiction_id"])
    if jurisdiction is not None:
        engine.recompute_committed_crew_hours(jurisdiction)
    return entity_response(call)
