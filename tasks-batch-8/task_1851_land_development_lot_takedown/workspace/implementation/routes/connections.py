"""UtilityConnection endpoints (PRD 3.9): impact fees and connection scheduling."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_CONNECTION_INVALID_STATE,
    ERR_PHASE_NOT_READY_FOR_CONNECTIONS,
    ERR_PROVIDER_CAPACITY_EXCEEDED,
    ERR_SCHEDULE_DATE_IN_PAST,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services import calculations as calc
from services.core import new_record, touch
from util import CLOCK, parse_dt
from validate import check_body_fk_exists, get_body, req_datetime, req_str, require_path

bp = Blueprint("connections", __name__)


@bp.post("/utility-connections")
def create_connection():
    authorized(["DeveloperOperator"])
    body = get_body()
    # Priority 3: body FK existence in declared order — lot_id, provider_id
    check_body_fk_exists("lots", body, "lot_id")
    check_body_fk_exists("providers", body, "provider_id")
    # Priority 4: shape
    lot_id = req_str(body, "lot_id")
    provider_id = req_str(body, "provider_id")
    scheduled_date = req_datetime(body, "scheduled_date")
    lot = db["lots"][lot_id]
    provider = db["providers"][provider_id]
    # Priority 10 (referential): the lot's phase must be ACTIVE
    phase = db["phases"].get(lot["phase_id"])
    if phase is None or phase["status"] != "ACTIVE":
        raise_error(ERR_PHASE_NOT_READY_FOR_CONNECTIONS,
                    "the lot's phase is not ACTIVE")
    # Impact fee computed and frozen at creation time
    fee = calc.impact_fee_cents(provider["utility_type"], CLOCK.today())
    rec = new_record("connections", {
        "lot_id": lot_id,
        "provider_id": provider_id,
        "scheduled_date": scheduled_date,
        "impact_fee_cents": fee,
        "status": "REQUESTED",
    })
    return success_object(public(rec), status=201)


@bp.get("/utility-connections")
def list_connections():
    return list_response("connections", {
        "lot_id": request.args.get("lot_id"),
        "provider_id": request.args.get("provider_id"),
        "status": request.args.get("status"),
    })


@bp.get("/utility-connections/<rid>")
def get_connection(rid):
    return get_one("connections", rid)


@bp.post("/utility-connections/<rid>/schedule")
def schedule_connection(rid):
    authorized(["MunicipalClerk"])
    conn = require_path("connections", rid)
    # Priority 6 (state)
    if conn["status"] != "REQUESTED":
        raise_error(ERR_CONNECTION_INVALID_STATE, "schedule requires REQUESTED")
    # Priority 8 (temporal): same-day scheduling is fine; a past calendar day fails
    sched_day = parse_dt(conn["scheduled_date"]).date()
    if sched_day < CLOCK.today():
        raise_error(ERR_SCHEDULE_DATE_IN_PAST,
                    "scheduled_date's calendar day is before the current day")
    # Priority 9 (capacity): count same-day SCHEDULED/CONNECTED connections of
    # the provider; reject when the day is already full
    provider = db["providers"][conn["provider_id"]]
    used = sum(
        1 for c in db["connections"].values()
        if c["provider_id"] == conn["provider_id"]
        and c["status"] in ("SCHEDULED", "CONNECTED")
        and parse_dt(c["scheduled_date"]).date() == sched_day
    )
    if used >= provider["max_connections_per_day"]:
        raise_error(ERR_PROVIDER_CAPACITY_EXCEEDED,
                    "provider daily connection capacity reached for that day")
    conn["status"] = "SCHEDULED"
    touch(conn)
    return success_object(public(conn))


@bp.post("/utility-connections/<rid>/mark-connected")
def mark_connected(rid):
    authorized(["MunicipalClerk"])
    conn = require_path("connections", rid)
    if conn["status"] != "SCHEDULED":
        raise_error(ERR_CONNECTION_INVALID_STATE, "mark-connected requires SCHEDULED")
    conn["status"] = "CONNECTED"
    touch(conn)
    return success_object(public(conn))


@bp.post("/utility-connections/<rid>/cancel")
def cancel_connection(rid):
    authorized(["DeveloperOperator"])
    conn = require_path("connections", rid)
    if conn["status"] not in ("REQUESTED", "SCHEDULED"):
        raise_error(ERR_CONNECTION_INVALID_STATE, "cancel requires REQUESTED or SCHEDULED")
    # Cancelling a SCHEDULED connection frees the provider's daily slot (capacity
    # is counted live from SCHEDULED/CONNECTED rows, so no counter to adjust)
    conn["status"] = "CANCELLED"
    touch(conn)
    return success_object(public(conn))
