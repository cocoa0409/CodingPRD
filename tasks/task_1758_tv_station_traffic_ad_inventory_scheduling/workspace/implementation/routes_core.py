"""Core resource routes: advertisers, programs, avail weeks/units, copy
instructions, and log-day creation/listing. Validation pipeline order per
PRD §2.10: auth -> role -> existence -> state -> date window -> reference ->
political -> capacity -> separation -> copy -> reconcile -> credit -> field
sanity -> OCC."""

from flask import Blueprint

import domain
from domain import (
    DAYPART_CODES, PRODUCT_CATEGORIES, SPOT_LENGTHS,
    date_in_week, recompute_budget,  # noqa: F401  (re-exported helpers)
)
from helpers import (
    auth, fail, json_body, list_response, new_record, ok_object, opt_bool,
    opt_int, opt_string, parse_iso_date, query_filter, query_int_filter,
    req_date_str, req_enum, req_int, req_number, req_string, req_time_hhmm,
    touch,
)
from serializers import (
    ser_advertiser, ser_avail_unit, ser_avail_week, ser_copy_instruction,
    ser_log_day, ser_order, ser_order_line, ser_program, ser_spot,
)
from store import db

bp = Blueprint("core", __name__)

READERS_ALL = ("SalesRep", "TrafficManager", "CopyCoordinator", "BillingClerk", "StationAdmin")
READERS_OPS = ("SalesRep", "TrafficManager", "BillingClerk", "StationAdmin")


def get_advertiser_or_404(advertiser_id):
    rec = db.advertisers.get(advertiser_id)
    if rec is None:
        fail("ERR_NOT_FOUND", "advertiser %s not found" % advertiser_id)
    return rec


def get_program_or_404(program_id):
    rec = db.programs.get(program_id)
    if rec is None:
        fail("ERR_NOT_FOUND", "program %s not found" % program_id)
    return rec


def get_week_or_404(week_id):
    rec = db.avail_weeks.get(week_id)
    if rec is None:
        fail("ERR_NOT_FOUND", "avail week %s not found" % week_id)
    return rec


def get_unit_or_404(unit_id):
    rec = db.avail_units.get(unit_id)
    if rec is None:
        fail("ERR_NOT_FOUND", "avail unit %s not found" % unit_id)
    return rec


def get_copy_or_404(copy_id):
    rec = db.copy_instructions.get(copy_id)
    if rec is None:
        fail("ERR_NOT_FOUND", "copy instruction %s not found" % copy_id)
    return rec


# ---------------------------------------------------------------------------
# Advertisers (PRD §3.1)
# ---------------------------------------------------------------------------

@bp.post("/traffic/advertisers")
def create_advertiser():
    auth("SalesRep")
    data = json_body()
    name = req_string(data, "name")
    agency_name = opt_string(data, "agency_name", "")
    product_category = req_enum(data, "product_category", PRODUCT_CATEGORIES)
    credit_limit_cents = req_int(data, "credit_limit_cents", min_value=0)
    rec = new_record()
    rec.update(
        {
            "name": name,
            "agency_name": agency_name,
            "product_category": product_category,
            "credit_limit_cents": credit_limit_cents,
        }
    )
    db.advertisers[rec["id"]] = rec
    return ok_object(ser_advertiser(rec), 201)


@bp.get("/traffic/advertisers")
def list_advertisers():
    auth(*READERS_ALL)
    items = list(db.advertisers.values())
    category = query_filter("product_category")
    if category is not None:
        items = [a for a in items if a["product_category"] == category]
    return list_response(items, ser_advertiser)


@bp.get("/traffic/advertisers/<advertiser_id>")
def get_advertiser(advertiser_id):
    auth(*READERS_ALL)
    return ok_object(ser_advertiser(get_advertiser_or_404(advertiser_id)))


@bp.get("/traffic/advertisers/<advertiser_id>/orders")
def list_advertiser_orders(advertiser_id):
    auth("SalesRep", "TrafficManager", "BillingClerk", "StationAdmin")
    get_advertiser_or_404(advertiser_id)
    items = [o for o in db.orders.values() if o["advertiser_id"] == advertiser_id]
    status = query_filter("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return list_response(items, ser_order)


@bp.get("/traffic/advertisers/<advertiser_id>/copy-instructions")
def list_advertiser_copy(advertiser_id):
    auth("SalesRep", "TrafficManager", "CopyCoordinator")
    get_advertiser_or_404(advertiser_id)
    items = [
        c for c in db.copy_instructions.values() if c["advertiser_id"] == advertiser_id
    ]
    status = query_filter("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    length = query_int_filter("length_seconds")
    if length is not None:
        items = [c for c in items if c["length_seconds"] == length]
    return list_response(items, ser_copy_instruction)


# ---------------------------------------------------------------------------
# Programs (PRD §3.2)
# ---------------------------------------------------------------------------

@bp.post("/traffic/programs")
def create_program():
    auth("TrafficManager")
    data = json_body()
    title = req_string(data, "title")
    daypart_code = req_enum(data, "daypart_code", DAYPART_CODES)
    airs_weekday = req_int(data, "airs_weekday", min_value=1, max_value=7)
    start_time_local = req_time_hhmm(data, "start_time_local")
    duration_minutes = req_int(data, "duration_minutes", min_value=5)
    rating_estimate = req_number(data, "rating_estimate", min_value=0)
    is_political_window = opt_bool(data, "is_political_window", False)
    rec = new_record()
    rec.update(
        {
            "title": title,
            "daypart_code": daypart_code,
            "airs_weekday": airs_weekday,
            "start_time_local": start_time_local,
            "duration_minutes": duration_minutes,
            "rating_estimate": rating_estimate,
            "is_political_window": is_political_window,
        }
    )
    db.programs[rec["id"]] = rec
    return ok_object(ser_program(rec), 201)


@bp.get("/traffic/programs")
def list_programs():
    auth(*READERS_OPS)
    items = list(db.programs.values())
    daypart = query_filter("daypart_code")
    if daypart is not None:
        items = [p for p in items if p["daypart_code"] == daypart]
    weekday = query_int_filter("airs_weekday")
    if weekday is not None:
        items = [p for p in items if p["airs_weekday"] == weekday]
    return list_response(items, ser_program)


@bp.get("/traffic/programs/<program_id>")
def get_program(program_id):
    auth(*READERS_OPS)
    return ok_object(ser_program(get_program_or_404(program_id)))


@bp.get("/traffic/programs/<program_id>/order-lines")
def list_program_order_lines(program_id):
    auth(*READERS_OPS)
    get_program_or_404(program_id)
    items = [l for l in db.order_lines.values() if l["program_id"] == program_id]
    status = query_filter("status")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    return list_response(items, ser_order_line)


# ---------------------------------------------------------------------------
# Avail weeks and avail units (PRD §3.2)
# ---------------------------------------------------------------------------

@bp.post("/traffic/avail-weeks")
def create_avail_week():
    auth("TrafficManager")
    data = json_body()
    week_start_date = req_date_str(data, "week_start_date")
    rec = new_record()
    rec.update({"week_start_date": week_start_date, "status": "OPEN"})
    db.avail_weeks[rec["id"]] = rec
    return ok_object(ser_avail_week(rec), 201)


@bp.get("/traffic/avail-weeks")
def list_avail_weeks():
    auth(*READERS_OPS)
    items = list(db.avail_weeks.values())
    status = query_filter("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    return list_response(items, ser_avail_week)


@bp.get("/traffic/avail-weeks/<week_id>")
def get_avail_week(week_id):
    auth(*READERS_OPS)
    return ok_object(ser_avail_week(get_week_or_404(week_id)))


@bp.post("/traffic/avail-weeks/<week_id>/avail-units")
def create_avail_unit(week_id):
    auth("TrafficManager")
    week = get_week_or_404(week_id)  # path id first (PRD §2.9)
    data = json_body()
    program_id = data.get("program_id")
    if program_id is not None:
        get_program_or_404(program_id)  # body *_id resolution -> 404
    # Date-window coherence (priority 5) runs before field sanity (13).
    air_date_raw = data.get("air_date")
    air_date = None
    if isinstance(air_date_raw, str):
        try:
            air_date = parse_iso_date(air_date_raw, "air_date").isoformat()
        except Exception:
            air_date = None  # malformed: field sanity below reports 400
    if air_date is not None:
        if not date_in_week(week, air_date):
            fail(
                "ERR_DATE_WINDOW",
                "air_date %s falls outside the owning broadcast week" % air_date,
            )
        if program_id is not None:
            program = db.programs.get(program_id)
            if program is not None and parse_iso_date(air_date).isoweekday() != program["airs_weekday"]:
                fail(
                    "ERR_DATE_WINDOW",
                    "air_date %s does not match the program's airs_weekday" % air_date,
                )
    # Field-level sanity (priority 13).
    if program_id is None:
        fail("ERR_INVALID_REQUEST", "program_id is required")
    if air_date is None:
        fail("ERR_INVALID_REQUEST", "air_date is required and must be an ISO date (YYYY-MM-DD)")
    break_position = req_int(data, "break_position", min_value=1)
    total_seconds = req_int(data, "total_seconds", min_value=1)
    reserved = opt_int(data, "reserved_political_seconds", 0, min_value=0)
    if reserved > total_seconds:
        fail(
            "ERR_INVALID_REQUEST",
            "reserved_political_seconds must not exceed total_seconds",
        )
    rec = new_record()
    rec.update(
        {
            "avail_week_id": week["id"],
            "program_id": program_id,
            "air_date": air_date,
            "break_position": break_position,
            "total_seconds": total_seconds,
            "reserved_political_seconds": reserved,
            "booked_commercial_seconds": 0,
            "booked_political_seconds": 0,
        }
    )
    db.avail_units[rec["id"]] = rec
    return ok_object(ser_avail_unit(rec), 201)


def _filter_units(items):
    program_id = query_filter("program_id")
    if program_id is not None:
        items = [u for u in items if u["program_id"] == program_id]
    air_date = query_filter("air_date")
    if air_date is not None:
        items = [u for u in items if u["air_date"] == air_date]
    return items


@bp.get("/traffic/avail-weeks/<week_id>/avail-units")
def list_week_avail_units(week_id):
    auth(*READERS_OPS)
    get_week_or_404(week_id)
    items = [u for u in db.avail_units.values() if u["avail_week_id"] == week_id]
    return list_response(_filter_units(items), ser_avail_unit)


@bp.get("/traffic/avail-units/<unit_id>")
def get_avail_unit(unit_id):
    auth(*READERS_OPS)
    return ok_object(ser_avail_unit(get_unit_or_404(unit_id)))


@bp.get("/traffic/avail-units")
def list_avail_units():
    auth(*READERS_OPS)
    items = list(db.avail_units.values())
    week_id = query_filter("avail_week_id")
    if week_id is not None:
        items = [u for u in items if u["avail_week_id"] == week_id]
    return list_response(_filter_units(items), ser_avail_unit)


@bp.get("/traffic/avail-units/<unit_id>/spots")
def list_avail_unit_spots(unit_id):
    auth(*READERS_OPS)
    get_unit_or_404(unit_id)
    items = [s for s in db.spots.values() if s["avail_unit_id"] == unit_id]
    status = query_filter("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_response(items, ser_spot)


# ---------------------------------------------------------------------------
# Log days — creation and reads (finalize/reconcile live in routes_logs.py)
# ---------------------------------------------------------------------------

@bp.post("/traffic/avail-weeks/<week_id>/log-days")
def create_log_day(week_id):
    auth("TrafficManager")
    week = get_week_or_404(week_id)
    data = json_body()
    log_date_raw = data.get("log_date")
    log_date = None
    if isinstance(log_date_raw, str):
        try:
            log_date = parse_iso_date(log_date_raw, "log_date").isoformat()
        except Exception:
            log_date = None
    if log_date is not None and not date_in_week(week, log_date):
        fail(
            "ERR_DATE_WINDOW",
            "log_date %s falls outside the owning broadcast week" % log_date,
        )
    if log_date is None:
        fail("ERR_INVALID_REQUEST", "log_date is required and must be an ISO date (YYYY-MM-DD)")
    rec = new_record()
    rec.update({"avail_week_id": week["id"], "log_date": log_date, "status": "DRAFT"})
    db.log_days[rec["id"]] = rec
    return ok_object(ser_log_day(rec), 201)


@bp.get("/traffic/avail-weeks/<week_id>/log-days")
def list_week_log_days(week_id):
    auth("TrafficManager", "BillingClerk", "StationAdmin")
    get_week_or_404(week_id)
    items = [l for l in db.log_days.values() if l["avail_week_id"] == week_id]
    status = query_filter("status")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    return list_response(items, ser_log_day)


@bp.get("/traffic/log-days/<log_day_id>")
def get_log_day(log_day_id):
    auth(*READERS_OPS)
    rec = db.log_days.get(log_day_id)
    if rec is None:
        fail("ERR_NOT_FOUND", "log day %s not found" % log_day_id)
    return ok_object(ser_log_day(rec))


# ---------------------------------------------------------------------------
# Copy instructions (PRD §3.3)
# ---------------------------------------------------------------------------

@bp.post("/traffic/copy-instructions")
def create_copy_instruction():
    auth("CopyCoordinator")
    data = json_body()
    advertiser_id = data.get("advertiser_id")
    if advertiser_id is not None:
        get_advertiser_or_404(advertiser_id)
    if advertiser_id is None:
        fail("ERR_INVALID_REQUEST", "advertiser_id is required")
    length_seconds = req_int(data, "length_seconds", domain=SPOT_LENGTHS)
    rotation_weight = opt_int(data, "rotation_weight", 1, min_value=1)
    rec = new_record()
    rec.update(
        {
            "advertiser_id": advertiser_id,
            "length_seconds": length_seconds,
            "rotation_weight": rotation_weight,
            "status": "PENDING",
        }
    )
    db.copy_instructions[rec["id"]] = rec
    return ok_object(ser_copy_instruction(rec), 201)


@bp.get("/traffic/copy-instructions/<copy_id>")
def get_copy_instruction(copy_id):
    auth("SalesRep", "TrafficManager", "CopyCoordinator")
    return ok_object(ser_copy_instruction(get_copy_or_404(copy_id)))


@bp.post("/traffic/copy-instructions/<copy_id>/receive")
def receive_copy(copy_id):
    auth("CopyCoordinator")
    rec = get_copy_or_404(copy_id)
    if rec["status"] != "PENDING":
        fail(
            "ERR_INVALID_STATE",
            "copy instruction in status %s cannot be received" % rec["status"],
        )
    rec["status"] = "RECEIVED"
    touch(rec)
    return ok_object(ser_copy_instruction(rec))


@bp.post("/traffic/copy-instructions/<copy_id>/expire")
def expire_copy(copy_id):
    auth("CopyCoordinator")
    rec = get_copy_or_404(copy_id)
    if rec["status"] not in ("PENDING", "RECEIVED"):
        fail(
            "ERR_INVALID_STATE",
            "copy instruction in status %s cannot be expired" % rec["status"],
        )
    if rec["status"] == "RECEIVED":
        # Guard: copy a FINALIZED log still depends on cannot be withdrawn —
        # a SCHEDULED spot referencing it on a finalized log date blocks expiry.
        for spot in db.spots.values():
            if spot["copy_instruction_id"] != rec["id"] or spot["status"] != "SCHEDULED":
                continue
            if any(
                ld["log_date"] == spot["scheduled_air_date"] and ld["status"] == "FINALIZED"
                for ld in db.log_days.values()
            ):
                fail(
                    "ERR_INVALID_STATE",
                    "copy is referenced by a finalized log and cannot be expired",
                )
    rec["status"] = "EXPIRED"
    touch(rec)
    return ok_object(ser_copy_instruction(rec))


@bp.get("/traffic/copy-instructions/<copy_id>/spots")
def list_copy_spots(copy_id):
    auth("SalesRep", "TrafficManager", "CopyCoordinator")
    get_copy_or_404(copy_id)
    items = [s for s in db.spots.values() if s["copy_instruction_id"] == copy_id]
    status = query_filter("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_response(items, ser_spot)
