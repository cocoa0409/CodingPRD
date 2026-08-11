"""Wellness program endpoints."""
from flask import Blueprint

import db
import errors
from auth import require_account_owner, require_roles
from clock import clock
from respond import success
from services import calc
from services.domain import get_or_404, recompute_draft_invoices_for_program
from validate import (apply_filters, json_body, paginate, req_date, req_enum,
                      req_hhmm, req_int, req_number, req_str, opt_str,
                      opt_int_field)

bp = Blueprint("wellness_programs", __name__)

CADENCES = ("WEEKLY", "BIWEEKLY", "MONTHLY")


def _hhmm_to_minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _load_owned_program(pid):
    program = get_or_404("wellness_programs", pid, "WellnessProgram")
    require_account_owner(program["corporate_account_id"])
    return program


@bp.post("/chair-massage/wellness-programs")
@require_roles("Organizer")
def create_program():
    body = json_body()
    account_id = req_str(body, "corporate_account_id")
    get_or_404("corporate_accounts", account_id, "CorporateAccount")
    require_account_owner(account_id)
    name = req_str(body, "name")
    cadence = req_enum(body, "cadence", CADENCES)
    chair_count = req_int(body, "chair_count", min_v=1)
    slot_minutes = req_int(body, "slot_minutes", min_v=5)
    window_start_time = req_hhmm(body, "window_start_time")
    duration = req_int(body, "window_duration_minutes", min_v=1)
    discount = req_number(body, "recurrence_discount_pct", min_v=0.0, max_v=0.50)
    if duration < slot_minutes:
        raise errors.invalid_request(
            "window_duration_minutes must be >= slot_minutes")
    if duration % slot_minutes != 0:
        raise errors.unprocessable(
            errors.ERR_WINDOW_NOT_DIVISIBLE,
            "window_duration_minutes must be an exact multiple of slot_minutes")
    program = db.stamp_new({
        "id": db.new_id(),
        "corporate_account_id": account_id,
        "name": name,
        "cadence": cadence,
        "chair_count": chair_count,
        "slot_minutes": slot_minutes,
        "window_start_time": window_start_time,
        "window_duration_minutes": duration,
        "recurrence_discount_pct": discount,
        "status": "ACTIVE",
        "next_occurrence_date": None,
        "occurrences_materialized": 0,
    })
    db.insert("wellness_programs", program)
    program["next_occurrence_date"] = calc.next_occurrence_from_clock(
        program, clock.today_date()).isoformat()
    return success(db.public(program), status=201)


@bp.get("/chair-massage/wellness-programs")
@require_roles("PlatformAdmin", "Organizer")
def list_programs():
    items = db.all_sorted("wellness_programs")
    items = apply_filters(items, {
        "status": (lambda e: e["status"], "str"),
        "corporate_account_id": (lambda e: e["corporate_account_id"], "str"),
    })
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)


@bp.get("/chair-massage/wellness-programs/<pid>")
@require_roles("PlatformAdmin", "Organizer")
def get_program(pid):
    program = _load_owned_program(pid)
    return success(db.public(program))


@bp.post("/chair-massage/wellness-programs/<pid>/pause")
@require_roles("Organizer")
def pause_program(pid):
    program = _load_owned_program(pid)
    if program["status"] != "ACTIVE":
        raise errors.invalid_state("Only an ACTIVE program can be paused")
    program["status"] = "PAUSED"
    program["next_occurrence_date"] = None
    db.touch(program)
    return success(db.public(program))


@bp.post("/chair-massage/wellness-programs/<pid>/resume")
@require_roles("Organizer")
def resume_program(pid):
    program = _load_owned_program(pid)
    if program["status"] != "PAUSED":
        raise errors.invalid_state("Only a PAUSED program can be resumed")
    program["status"] = "ACTIVE"
    program["next_occurrence_date"] = calc.next_occurrence_from_clock(
        program, clock.today_date()).isoformat()
    db.touch(program)
    return success(db.public(program))


@bp.post("/chair-massage/wellness-programs/<pid>/terminate")
@require_roles("Organizer")
def terminate_program(pid):
    program = _load_owned_program(pid)
    if program["status"] not in ("ACTIVE", "PAUSED"):
        raise errors.invalid_state("Only an ACTIVE or PAUSED program can be terminated")
    program["status"] = "TERMINATED"
    program["next_occurrence_date"] = None
    db.touch(program)
    # Recurrence tier flips to STANDARD on any still-DRAFT invoices of its bookings.
    recompute_draft_invoices_for_program(pid)
    return success(db.public(program))


@bp.get("/chair-massage/wellness-programs/<pid>/bookings")
@require_roles("PlatformAdmin", "Organizer")
def list_program_bookings(pid):
    _load_owned_program(pid)
    items = [b for b in db.all_sorted("bookings") if b["wellness_program_id"] == pid]
    items = apply_filters(items, {"status": (lambda e: e["status"], "str")})
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)


@bp.post("/chair-massage/wellness-programs/<pid>/materialize-occurrence")
@require_roles("Organizer", "PlatformAdmin")
def materialize_occurrence(pid):
    program = _load_owned_program(pid)
    if program["status"] != "ACTIVE":
        raise errors.invalid_state("Only an ACTIVE program can materialize occurrences")
    body = json_body()
    event_date = req_date(body, "event_date")
    # Idempotent per event_date: a second call returns the already-created booking.
    for existing in db.all_sorted("bookings"):
        if (existing["wellness_program_id"] == pid
                and existing["event_date"] == event_date
                and existing["booking_kind"] == "RECURRING_OCCURRENCE"):
            return success(db.public(existing), status=201)
    account = get_or_404("corporate_accounts", program["corporate_account_id"],
                         "CorporateAccount")
    region_id = opt_str(body, "region_id") or account["region_id"]
    site_address = opt_str(body, "site_address") or ""
    rate = opt_int_field(body, "per_minute_rate_cents")
    if rate is None:
        rate = 1
    if rate < 1:
        raise errors.invalid_request("per_minute_rate_cents must be >= 1")
    booking = db.stamp_new({
        "id": db.new_id(),
        "corporate_account_id": program["corporate_account_id"],
        "wellness_program_id": pid,
        "booking_kind": "RECURRING_OCCURRENCE",
        "region_id": region_id,
        "site_address": site_address,
        "event_date": event_date,
        "window_start_minutes": _hhmm_to_minutes(program["window_start_time"]),
        "window_duration_minutes": program["window_duration_minutes"],
        "chair_count": program["chair_count"],
        "slot_minutes": program["slot_minutes"],
        "per_minute_rate_cents": rate,
        "status": "DRAFT",
        "billing_status": "UNBILLED",
        "booked_chair_minutes": 0,
        "delivered_chair_minutes": 0,
        "cancellation_fee_cents": 0,
    })
    db.insert("bookings", booking)
    # Advance the program's schedule one cadence step past the occurrence,
    # keeping the strictly-after-today invariant.
    nxt = calc.cadence_successor(event_date, program["cadence"])
    today = clock.today_date()
    while nxt <= today:
        nxt = calc.cadence_successor(nxt.isoformat(), program["cadence"])
    program["next_occurrence_date"] = nxt.isoformat()
    program["occurrences_materialized"] += 1
    db.touch(program)
    return success(db.public(booking), status=201)
