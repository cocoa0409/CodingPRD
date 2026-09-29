from decimal import Decimal

from flask import Blueprint

import constants as C
import validators as V
from auth import authorize, authorize_action, current_user
from domain import apply_changes, recompute_bank_rollup, serialize_flight_bank, turns_of_bank
from envelope import filter_equals, paginate, respond_object
from errors import ApiError
from store import as_dt, db, new_record, ordered, require

bp = Blueprint("flight_banks", __name__)

BANK_ACTION_ROLES = {
    "PUBLISH": [C.ROLE_DUTY_OFFICER],
    "LOCK": [C.ROLE_STATION_MANAGER],
    "ARCHIVE": [C.ROLE_STATION_MANAGER],
}
STAFFING_ACTION_ROLES = {
    "SUBMIT": [C.ROLE_DUTY_OFFICER],
    "REVISE": [C.ROLE_DUTY_OFFICER],
    "APPROVE": [C.ROLE_STATION_MANAGER],
    "REJECT": [C.ROLE_STATION_MANAGER],
}
BANK_ENDPOINT_ROLES = [C.ROLE_DUTY_OFFICER, C.ROLE_STATION_MANAGER]


@bp.post("/flight-banks")
def create_flight_bank():
    authorize(BANK_ENDPOINT_ROLES)
    payload = V.body()

    station_id = V.req_string(payload, "station_id")
    bank_code = V.req_string(payload, "bank_code")
    season_code = V.req_enum(payload, "season_code", C.SEASONS)
    window_start = V.req_datetime(payload, "window_start")
    window_end = V.req_datetime(payload, "window_end")
    if as_dt(window_end) <= as_dt(window_start):
        raise ApiError("ERR_INVALID_REQUEST", "window_end must be strictly after window_start.")
    planned_headcount = V.opt_int(payload, "planned_headcount", 0, 0)

    station = require(db.stations, station_id, "Station")

    if station["status"] != "OPEN":
        raise ApiError("ERR_STATION_NOT_OPEN")
    if station["oversight_posture"] == "RESTRICTED":
        raise ApiError("ERR_STATION_POSTURE_RESTRICTED")
    for existing in db.flight_banks.values():
        if existing["station_id"] == station["id"] and existing["bank_code"] == bank_code:
            raise ApiError("ERR_DUPLICATE_CODE", "bank_code already exists at this station.")
    if season_code != station["season_code"]:
        raise ApiError("ERR_SEASON_MISMATCH")

    bank = new_record("FlightBank", {
        "station_id": station["id"],
        "bank_code": bank_code,
        "season_code": season_code,
        "window_start": window_start,
        "window_end": window_end,
        "bank_status": "DRAFT",
        "staffing_status": "DRAFT",
        "planned_headcount": planned_headcount,
        "required_headcount": 0,
        "turn_count": 0,
        "staffing_coverage_pct": Decimal("100.00"),
        "last_staffing_decision_by_user_id": None,
    })
    db.flight_banks[bank["id"]] = bank
    return respond_object(serialize_flight_bank(bank), 201)


@bp.get("/flight-banks/<flight_bank_id>")
def read_flight_bank(flight_bank_id):
    authorize(C.ALL_ROLES)
    bank = require(db.flight_banks, flight_bank_id, "FlightBank")
    return respond_object(serialize_flight_bank(bank))


@bp.get("/flight-banks")
def list_flight_banks():
    authorize(C.ALL_ROLES)
    records = filter_equals(db.flight_banks.values(), {
        "station_id": "station_id",
        "season_code": "season_code",
        "bank_status": "bank_status",
        "staffing_status": "staffing_status",
    })
    return paginate(ordered(records), serialize_flight_bank)


@bp.post("/flight-banks/<flight_bank_id>/lifecycle")
def flight_bank_lifecycle(flight_bank_id):
    payload = V.body()
    authorize_action(BANK_ENDPOINT_ROLES, BANK_ACTION_ROLES, payload.get("action"))
    bank = require(db.flight_banks, flight_bank_id, "FlightBank")
    action = V.req_enum(payload, "action", C.BANK_ACTIONS)

    station = db.stations[bank["station_id"]]
    live_turns = [t for t in turns_of_bank(bank["id"])
                  if t["status"] in ("SCHEDULED", "RESOURCED", "IN_PROGRESS")]

    if action == "PUBLISH":
        if bank["bank_status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE")
        recompute_bank_rollup(bank)
        if bank["turn_count"] < 1:
            raise ApiError("ERR_INVALID_STATE", "An empty bank cannot be published.")
        if station["status"] != "OPEN":
            raise ApiError("ERR_STATION_NOT_OPEN")
        apply_changes(bank, {"bank_status": "PUBLISHED"})
        recompute_bank_rollup(bank)
    elif action == "LOCK":
        if bank["bank_status"] != "PUBLISHED":
            raise ApiError("ERR_INVALID_STATE")
        if bank["staffing_status"] != "APPROVED":
            raise ApiError("ERR_INVALID_STATE", "The staffing plan is not approved.")
        apply_changes(bank, {"bank_status": "LOCKED"})
    else:  # ARCHIVE
        if bank["bank_status"] not in ("DRAFT", "PUBLISHED", "LOCKED"):
            raise ApiError("ERR_INVALID_STATE")
        if live_turns:
            raise ApiError("ERR_INVALID_STATE", "The bank still holds live turnarounds.")
        apply_changes(bank, {"bank_status": "ARCHIVED"})

    return respond_object(serialize_flight_bank(bank))


@bp.post("/flight-banks/<flight_bank_id>/staffing-transitions")
def flight_bank_staffing(flight_bank_id):
    payload = V.body()
    authorize_action(BANK_ENDPOINT_ROLES, STAFFING_ACTION_ROLES, payload.get("action"))
    bank = require(db.flight_banks, flight_bank_id, "FlightBank")
    action = V.req_enum(payload, "action", C.STAFFING_ACTIONS)
    planned_headcount = V.opt_int(payload, "planned_headcount", None, 0)

    station = db.stations[bank["station_id"]]

    if action == "SUBMIT":
        if bank["staffing_status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE")
        if bank["bank_status"] != "PUBLISHED":
            raise ApiError("ERR_BANK_NOT_PUBLISHED")
        recompute_bank_rollup(bank)
        apply_changes(bank, {"staffing_status": "SUBMITTED"})
    elif action == "APPROVE":
        if bank["staffing_status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE")
        if station["status"] != "OPEN":
            raise ApiError("ERR_STATION_NOT_OPEN")
        coverage = recompute_bank_rollup(bank)
        if coverage < C.APPROVE_MIN_COVERAGE_PCT:
            raise ApiError("ERR_STAFFING_COVERAGE_INSUFFICIENT")
        apply_changes(bank, {
            "staffing_status": "APPROVED",
            "last_staffing_decision_by_user_id": current_user(),
        })
    elif action == "REJECT":
        if bank["staffing_status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE")
        recompute_bank_rollup(bank)
        apply_changes(bank, {
            "staffing_status": "REVISION_REQUIRED",
            "last_staffing_decision_by_user_id": current_user(),
        })
    else:  # REVISE
        if bank["staffing_status"] != "REVISION_REQUIRED":
            raise ApiError("ERR_INVALID_STATE")
        if planned_headcount is not None:
            apply_changes(bank, {"planned_headcount": planned_headcount})
        recompute_bank_rollup(bank)
        apply_changes(bank, {"staffing_status": "DRAFT"})

    return respond_object(serialize_flight_bank(bank))
