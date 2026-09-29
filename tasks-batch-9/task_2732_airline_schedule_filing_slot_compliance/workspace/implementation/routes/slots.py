"""Slot series at coordinated airports, and the immutable utilization log."""
from flask import Blueprint

import calc
import cascades
import db
import derive
import reqval as rv
from db import mark, store
from errors import ApiError
from middleware import acting_role, acting_user, authenticate, require_ownership
from response import ok, written
from routes.common import (
    READ_ROLES,
    list_response,
    read_one,
    require_carrier_active,
    require_season_open,
)
from util import dt_of

bp = Blueprint("slots", __name__)

COORDINATOR = ("SlotCoordinator",)
PLANNER = ("NetworkPlanner",)


def _tod(instant):
    """The UTC time-of-day of an instant; a series' date is informational only."""
    return (instant.hour, instant.minute, instant.second, instant.microsecond)


def _series_conflict(station_id, season_id, movement_type, slot_time, mask):
    """A HELD series at the same station, season, movement and time-of-day, on a shared day."""
    target = _tod(dt_of(slot_time))
    digits = set(mask)
    for holding in store.values("slot_holdings"):
        if holding["holding_status"] != "HELD":
            continue
        if holding["station_id"] != station_id or holding["season_id"] != season_id:
            continue
        if holding["movement_type"] != movement_type:
            continue
        if _tod(dt_of(holding["slot_time_utc"])) != target:
            continue
        if digits & set(holding["days_of_week"]):
            return True
    return False


def _new_holding(station_id, season_id, carrier_id, movement_type, slot_time, mask,
                 series_weeks, historic, predecessor):
    return store.insert("slot_holdings", {
        "station_id": station_id,
        "season_id": season_id,
        "carrier_id": carrier_id,
        "movement_type": movement_type,
        "slot_time_utc": slot_time,
        "days_of_week": mask,
        "series_weeks": series_weeks,
        "historic_precedence": historic,
        "historic_predecessor_holding_id": predecessor,
        "holding_status": "HELD",
        "planned_operations": series_weeks * len(mask),
        "attached_operations": 0,
        "credited_operations": 0,
        "utilization_pct": 0.00,
        "utilization_pct_as_filed": 0.00,
        "at_risk_of_loss": False,
        "pending_transaction_id": None,
        "returned_reason": None,
        "returned_before_deadline": None,
        "retains_historic_precedence": None,
    })


@bp.post("/slot-holdings")
def create_slot_holding():
    authenticate(COORDINATOR)
    payload = rv.body()
    station_id = rv.req_str(payload, "station_id", 1)
    season_id = rv.req_str(payload, "season_id", 1)
    carrier_id = rv.req_str(payload, "carrier_id", 1)
    movement = rv.req_enum(payload, "movement_type", "movement_type")
    slot_time = rv.req_dt(payload, "slot_time_utc")
    mask = rv.req_days_of_week(payload, "days_of_week")
    weeks = rv.req_int(payload, "series_weeks", 1, 26)
    historic = rv.opt_bool(payload, "historic_precedence", False)
    predecessor = rv.opt_str(payload, "historic_predecessor_holding_id", 1)

    carrier = store.require("carriers", carrier_id)
    station = store.require("stations", station_id)
    season = store.require("seasons", season_id)
    if predecessor is not None:
        store.require("slot_holdings", predecessor)

    require_season_open(season)
    require_carrier_active(carrier)
    if station["coordination_level"] != derive.COORDINATED:
        raise ApiError("ERR_STATION_NOT_COORDINATED")
    if _series_conflict(station_id, season_id, movement, slot_time, mask):
        raise ApiError("ERR_SLOT_SERIES_CONFLICT")

    row = _new_holding(
        station_id, season_id, carrier_id, movement, slot_time, mask, weeks, historic, predecessor
    )
    return written(row, 201)


@bp.get("/slot-holdings/<slot_holding_id>")
def get_slot_holding(slot_holding_id):
    return ok(read_one("slot_holdings", slot_holding_id))


@bp.get("/slot-holdings")
def list_slot_holdings():
    authenticate(READ_ROLES)
    return list_response("slot_holdings", [
        ("station_id", rv.q_str("station_id")),
        ("season_id", rv.q_str("season_id")),
        ("carrier_id", rv.q_str("carrier_id")),
        ("historic_predecessor_holding_id", rv.q_str("historic_predecessor_holding_id")),
        ("pending_transaction_id", rv.q_str("pending_transaction_id")),
        ("holding_status", rv.q_enum("holding_status", "holding_status")),
        ("movement_type", rv.q_enum("movement_type", "movement_type")),
        ("at_risk_of_loss", rv.q_bool("at_risk_of_loss")),
        ("historic_precedence", rv.q_bool("historic_precedence")),
    ])


@bp.post("/slot-holdings/<slot_holding_id>/return")
def return_slot_holding(slot_holding_id):
    authenticate(PLANNER)
    holding = store.require("slot_holdings", slot_holding_id)
    payload = rv.body()
    reason = rv.req_str(payload, "reason", 1, 500)
    require_ownership(holding["carrier_id"])
    season = store.get("seasons", holding["season_id"])
    require_season_open(season)
    if holding["holding_status"] != "HELD":
        raise ApiError("ERR_SLOT_HOLDING_STATE_INVALID")
    if holding["pending_transaction_id"] is not None:
        raise ApiError("ERR_SLOT_ENCUMBERED")
    if db.now() > dt_of(season["slot_return_deadline_utc"]):
        raise ApiError("ERR_SLOT_RETURN_DEADLINE_PASSED")

    holding["holding_status"] = "RETURNED"
    holding["returned_reason"] = reason
    holding["returned_before_deadline"] = True
    holding["retains_historic_precedence"] = True
    mark(holding)
    cascades.detach_holding_from_legs(holding)
    return written(holding)


# --- utilization records --------------------------------------------------


@bp.post("/slot-utilization-records")
def create_utilization_record():
    authenticate(("NetworkPlanner", "SlotCoordinator"))
    payload = rv.body()
    holding_id = rv.req_str(payload, "slot_holding_id", 1)
    operation_date = rv.req_dt(payload, "operation_date")
    outcome = rv.req_enum(payload, "outcome", "outcome")
    if outcome == "RETURNED_IN_TIME":
        rv.bad("outcome RETURNED_IN_TIME is written only by the system's return cascade.")

    holding = store.require("slot_holdings", holding_id)
    season = store.get("seasons", holding["season_id"])
    if season is not None:
        moment = dt_of(operation_date)
        if moment < dt_of(season["start_date"]) or moment > dt_of(season["end_date"]):
            rv.bad("operation_date must fall inside the season window.")
    if holding["holding_status"] != "HELD":
        raise ApiError("ERR_SLOT_HOLDING_STATE_INVALID")
    if acting_role() == "NetworkPlanner" and holding["carrier_id"] != acting_user():
        raise ApiError("ERR_SLOT_CARRIER_MISMATCH")

    row = store.insert("slot_utilization_records", {
        "slot_holding_id": holding_id,
        "operation_date": operation_date,
        "outcome": outcome,
        "credited": outcome in calc.CREDITED_OUTCOMES,
        "recorded_by_user_id": acting_user(),
    }, versioned=False)
    return written(row, 201)


@bp.get("/slot-utilization-records/<slot_utilization_record_id>")
def get_utilization_record(slot_utilization_record_id):
    return ok(read_one("slot_utilization_records", slot_utilization_record_id))


@bp.get("/slot-utilization-records")
def list_utilization_records():
    authenticate(READ_ROLES)
    return list_response("slot_utilization_records", [
        ("slot_holding_id", rv.q_str("slot_holding_id")),
        ("outcome", rv.q_enum("outcome", "outcome")),
        ("credited", rv.q_bool("credited")),
    ])
