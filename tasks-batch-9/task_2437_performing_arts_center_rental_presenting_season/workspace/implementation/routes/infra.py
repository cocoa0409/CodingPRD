"""Season infrastructure: halls, counterparties, rate cards, inventory, reserve, clock."""

from flask import Blueprint

import derive
from envelope import array_response, object_response
from errors import ApiError
from helpers import (
    auth,
    body,
    opt_bool,
    opt_enum,
    opt_int,
    opt_num,
    page,
    query_filter,
    req_bool,
    req_dt,
    req_enum,
    req_int,
    req_num,
    req_str,
)
from lookup import (
    find_artist,
    find_client,
    find_department,
    find_engagement,
    find_equipment,
    find_space,
)
from store import ordered, public, stamp, store

bp = Blueprint("infra", __name__)

SPACE_STATUSES = ("ACTIVE", "OFFLINE")
DEPARTMENTS = ("STAGEHANDS", "ELECTRICS", "AUDIO", "WARDROBE")
EQUIPMENT_CATEGORIES = ("POWER_DISTRO", "DMX_NODE", "RIGGING_HARDWARE", "AUDIO_PACKAGE")
CREDIT_RATINGS = ("A", "B", "C")
ENTRY_TYPES = (
    "OPENING_BALANCE",
    "MANUAL_ADJUSTMENT",
    "SETTLEMENT_CONTRIBUTION",
    "EDUCATION_SUBSIDY_DRAW",
    "EDUCATION_SUBSIDY_REFUND",
)


# ---------------------------------------------------------------------------
# Performance spaces
# ---------------------------------------------------------------------------
@bp.post("/performance-spaces")
def create_space():
    auth("CenterAdmin")
    data = body()
    record = {
        "name": req_str(data, "name"),
        "seat_capacity": req_int(data, "seat_capacity", minimum=1),
        "base_facility_fee_cents": req_int(data, "base_facility_fee_cents", minimum=0),
        "load_in_day_fee_cents": req_int(data, "load_in_day_fee_cents", minimum=0),
        "changeover_buffer_minutes": req_int(data, "changeover_buffer_minutes", minimum=0),
        "rigging_capacity_kg": req_int(data, "rigging_capacity_kg", minimum=0),
        "house_power_amps": req_int(data, "house_power_amps", minimum=0),
        "dmx_universes": req_int(data, "dmx_universes", minimum=0),
        "status": opt_enum(data, "status", SPACE_STATUSES, "ACTIVE"),
    }
    stamp(record)
    store.spaces[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/performance-spaces/<space_id>")
def read_space(space_id):
    auth(
        "CenterAdmin",
        "ProgrammingDirector",
        "RentalManager",
        "TechnicalDirector",
        "BoxOfficeManager",
    )
    return object_response(public(find_space(space_id)))


# ---------------------------------------------------------------------------
# Artists
# ---------------------------------------------------------------------------
@bp.post("/artists")
def create_artist():
    auth("ProgrammingDirector")
    data = body()
    start_raw, start_dt = req_dt(data, "routing_window_start_utc")
    end_raw, end_dt = req_dt(data, "routing_window_end_utc")
    record = {
        "legal_name": req_str(data, "legal_name"),
        "agency_name": req_str(data, "agency_name"),
        "guarantee_floor_cents": req_int(data, "guarantee_floor_cents", minimum=0),
        "historical_sell_through_pct": req_num(
            data, "historical_sell_through_pct", minimum=0, maximum=1, max_decimals=4
        ),
        "routing_window_start_utc": start_raw,
        "routing_window_end_utc": end_raw,
        "min_days_between_engagements": req_int(
            data, "min_days_between_engagements", minimum=0
        ),
        "lifetime_guarantee_paid_cents": 0,
        "_routing_start": start_dt,
        "_routing_end": end_dt,
    }
    stamp(record)
    store.artists[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/artists/<artist_id>")
def read_artist(artist_id):
    user_id, role = auth("ProgrammingDirector", "ArtistRepresentative", "FinanceController")
    if role == "ArtistRepresentative" and user_id != artist_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    return object_response(public(find_artist(artist_id)))


# ---------------------------------------------------------------------------
# Rental clients
# ---------------------------------------------------------------------------
@bp.post("/rental-clients")
def create_client():
    auth("RentalManager")
    data = body()
    record = {
        "org_name": req_str(data, "org_name"),
        "contact_email": req_str(data, "contact_email"),
        "credit_rating": req_enum(data, "credit_rating", CREDIT_RATINGS),
        "is_nonprofit": req_bool(data, "is_nonprofit"),
        "outstanding_balance_cents": opt_int(data, "outstanding_balance_cents", 0),
    }
    stamp(record)
    store.clients[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/rental-clients/<client_id>")
def read_client(client_id):
    user_id, role = auth("RentalManager", "RentalClientContact", "FinanceController")
    if role == "RentalClientContact" and user_id != client_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    return object_response(public(find_client(client_id)))


# ---------------------------------------------------------------------------
# Union departments
# ---------------------------------------------------------------------------
@bp.post("/union-departments")
def create_department():
    auth("CenterAdmin")
    data = body()
    department = req_enum(data, "department", DEPARTMENTS)
    record = {
        "department": department,
        "roster_size": req_int(data, "roster_size", minimum=1),
        "straight_hourly_rate_cents": req_int(data, "straight_hourly_rate_cents", minimum=1),
        "overtime_multiplier": opt_num(data, "overtime_multiplier", 1.5, minimum=0),
        "doubletime_multiplier": opt_num(data, "doubletime_multiplier", 2.0, minimum=0),
        "call_minimum_hours": opt_num(data, "call_minimum_hours", 4, minimum=0),
        "meal_penalty_cents": opt_int(data, "meal_penalty_cents", 3500, minimum=0),
    }
    for existing in store.departments.values():
        if existing["department"] == department:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "Department '%s' is already registered." % department,
            )
    stamp(record)
    store.departments[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/union-departments/<department_id>")
def read_department(department_id):
    auth("CenterAdmin", "TechnicalDirector", "FinanceController")
    return object_response(public(find_department(department_id)))


@bp.get("/union-departments/<department_id>/labor-calls")
def list_department_calls(department_id):
    auth("CenterAdmin", "TechnicalDirector", "FinanceController")
    department = find_department(department_id)
    items = [
        c for c in store.calls.values() if c["union_department_id"] == department["id"]
    ]
    status = query_filter("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    window, meta = page(ordered(items))
    return array_response([public(c) for c in window], meta)


# ---------------------------------------------------------------------------
# Equipment inventory
# ---------------------------------------------------------------------------
@bp.post("/equipment-items")
def create_equipment():
    auth("CenterAdmin")
    data = body()
    record = {
        "category": req_enum(data, "category", EQUIPMENT_CATEGORIES),
        "model_name": req_str(data, "model_name"),
        "on_hand_qty": req_int(data, "on_hand_qty", minimum=0),
        "reserved_qty": 0,
        "daily_rate_cents": req_int(data, "daily_rate_cents", minimum=0),
        "replacement_value_cents": req_int(data, "replacement_value_cents", minimum=0),
        "reserve_funded": opt_bool(data, "reserve_funded", False),
    }
    stamp(record)
    store.equipment[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/equipment-items/<item_id>")
def read_equipment(item_id):
    auth("CenterAdmin", "TechnicalDirector")
    return object_response(public(find_equipment(item_id)))


@bp.get("/equipment-items/<item_id>/rental-lines")
def list_item_lines(item_id):
    auth("CenterAdmin", "TechnicalDirector")
    item = find_equipment(item_id)
    items = [l for l in store.lines.values() if l["equipment_item_id"] == item["id"]]
    status = query_filter("status")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    window, meta = page(ordered(items))
    return array_response([public(l) for l in window], meta)


# ---------------------------------------------------------------------------
# Reserve ledger
# ---------------------------------------------------------------------------
@bp.post("/reserve-ledger-entries")
def create_ledger_entry():
    auth("CenterAdmin")
    data = body()
    engagement_id = data.get("engagement_id")
    if engagement_id is not None:
        find_engagement(engagement_id)
    entry_type = req_enum(data, "entry_type", ENTRY_TYPES)
    amount_cents = req_int(data, "amount_cents")
    memo = req_str(data, "memo")
    entry = derive.append_ledger(entry_type, amount_cents, memo, engagement_id)
    return object_response(public(entry), 201)


@bp.get("/reserve-ledger-entries")
def list_ledger_entries():
    auth("CenterAdmin", "FinanceController")
    items = derive.ledger_entries()
    entry_type = query_filter("entry_type")
    if entry_type is not None:
        items = [e for e in items if e["entry_type"] == entry_type]
    engagement_id = query_filter("engagement_id")
    if engagement_id is not None:
        items = [e for e in items if e["engagement_id"] == engagement_id]
    window, meta = page(items)
    return array_response([public(e) for e in window], meta)


@bp.get("/engagements/<engagement_id>/reserve-ledger-entries")
def list_engagement_ledger_entries(engagement_id):
    auth("CenterAdmin", "FinanceController")
    engagement = find_engagement(engagement_id)
    items = [e for e in derive.ledger_entries() if e["engagement_id"] == engagement["id"]]
    entry_type = query_filter("entry_type")
    if entry_type is not None:
        items = [e for e in items if e["entry_type"] == entry_type]
    window, meta = page(items)
    return array_response([public(e) for e in window], meta)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    auth("CenterAdmin")
    data = body()
    raw, parsed = req_dt(data, "to_iso8601")
    store.clock_raw = raw
    store.clock_dt = parsed
    return object_response({"current_utc": raw})
