"""Lockout / recurring contract routes (PRD §3.8)."""
from datetime import datetime, timezone, timedelta

from flask import Blueprint, request

from db import db, clock_now, new_id, now_iso_millis, db_iso
from errors import err
from middleware import get_principal, require_roles
from helpers import (
    get_json_body, require_str, require_int, get_pagination, paginate,
    get_or_404, stamp_common, touch,
)
from response import success_object, success_array
from serialize import public, public_list
from timeutil import parse_iso
from services import calc
from services import booking_logic as bl

bp = Blueprint("lockout_contracts", __name__)

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


def _get_zone(tz_name):
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return timezone.utc


def _parse_hhmm(value):
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        raise err("ERR_INVALID_REQUEST", "time must be HH:MM")
    try:
        hh = int(value[0:2])
        mm = int(value[3:5])
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "time must be HH:MM")
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise err("ERR_INVALID_REQUEST", "time out of range")
    return hh, mm


@bp.route("/studio/lockout-contracts", methods=["POST"])
def create_contract():
    principal = get_principal()
    require_roles(principal, {"StudioManager"})
    body = get_json_body()
    studio_id = require_str(body, "studio_id")
    room_id = require_str(body, "room_id")
    client_id = require_str(body, "client_id")
    weekday_mask = body.get("weekday_mask")
    daily_start_local = require_str(body, "daily_start_local")
    daily_end_local = require_str(body, "daily_end_local")
    window_start_raw = require_str(body, "window_start_date")
    window_end_raw = require_str(body, "window_end_date")

    # Existence of body FKs (left-to-right).
    get_or_404(db.studios, studio_id, "studio")
    get_or_404(db.rooms, room_id, "room")
    get_or_404(db.clients, client_id, "client")

    # Structural: weekday_mask must be a list.
    if weekday_mask is None or not isinstance(weekday_mask, list):
        raise err("ERR_INVALID_REQUEST", "weekday_mask must be a list")
    for v in weekday_mask:
        if isinstance(v, bool) or not isinstance(v, int):
            raise err("ERR_INVALID_REQUEST", "weekday_mask entries must be integers")

    # Semantic: non-empty, each in 1..7 (ERR_VALIDATION).
    if len(weekday_mask) == 0:
        raise err("ERR_VALIDATION", "weekday_mask must be non-empty")
    for v in weekday_mask:
        if not (1 <= v <= 7):
            raise err("ERR_VALIDATION", "weekday_mask entries must be in 1..7")

    sh, sm = _parse_hhmm(daily_start_local)
    eh, em = _parse_hhmm(daily_end_local)

    window_start = parse_iso(window_start_raw)
    window_end = parse_iso(window_end_raw)

    # Temporal: daily_end_local after daily_start_local (PRD §3.8).
    if (eh, em) <= (sh, sm):
        raise err("ERR_INVALID_TIME_RANGE", "daily_end_local must be after daily_start_local")

    contract = {
        "studio_id": studio_id,
        "room_id": room_id,
        "client_id": client_id,
        "weekday_mask": list(weekday_mask),
        "daily_start_local": daily_start_local,
        "daily_end_local": daily_end_local,
        "window_start_date": db_iso(window_start),
        "window_end_date": db_iso(window_end),
        "status": "DRAFT",
        "occurrences_generated": 0,
    }
    stamp_common(contract)
    db.lockout_contracts[contract["id"]] = contract
    return success_object(public(contract), status=201)


@bp.route("/studio/lockout-contracts/<cid>", methods=["GET"])
def get_contract(cid):
    principal = get_principal()
    require_roles(principal, {"StudioManager", "Client"})
    contract = get_or_404(db.lockout_contracts, cid, "lockout contract")
    if principal.role == "Client" and contract["client_id"] != principal.user_id:
        raise err("ERR_FORBIDDEN", "client may only access their own contracts")
    return success_object(public(contract))


@bp.route("/studio/lockout-contracts", methods=["GET"])
def list_contracts():
    principal = get_principal()
    require_roles(principal, {"StudioManager"})
    contracts = list(db.lockout_contracts.values())
    for key in ("studio_id", "room_id", "client_id"):
        val = request.args.get(key)
        if val is not None:
            contracts = [c for c in contracts if c[key] == val]
    limit, offset = get_pagination()
    page, total = paginate(contracts, limit, offset)
    return success_array(public_list(page), limit, offset, total)


def _occurrence_windows(contract, studio):
    """Generate (start_dt_utc, end_dt_utc) per masked weekday in the window."""
    zone = _get_zone(studio["timezone"])
    sh, sm = _parse_hhmm(contract["daily_start_local"])
    eh, em = _parse_hhmm(contract["daily_end_local"])
    mask = set(contract["weekday_mask"])

    start_date = parse_iso(contract["window_start_date"]).date()
    end_date = parse_iso(contract["window_end_date"]).date()

    windows = []
    d = start_date
    while d <= end_date:
        # ISO weekday: Monday=1 .. Sunday=7
        if d.isoweekday() in mask:
            local_start = datetime(d.year, d.month, d.day, sh, sm, tzinfo=zone)
            local_end = datetime(d.year, d.month, d.day, eh, em, tzinfo=zone)
            windows.append((local_start.astimezone(timezone.utc),
                            local_end.astimezone(timezone.utc)))
        d = d + timedelta(days=1)
    return windows


@bp.route("/studio/lockout-contracts/<cid>/activate", methods=["POST"])
def activate_contract(cid):
    principal = get_principal()
    require_roles(principal, {"StudioManager"})
    contract = get_or_404(db.lockout_contracts, cid, "lockout contract")
    body = get_json_body()
    expected_room_version = require_int(body, "expected_room_version")

    # State: contract must be DRAFT.
    if contract["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "contract is not DRAFT")

    room = db.rooms[contract["room_id"]]

    # OCC (priority 6, after state): expected_room_version vs live room version.
    if expected_room_version != room["version"]:
        raise err("ERR_STALE_VERSION", "expected_room_version does not match room version")

    # Room must be OPEN.
    if room["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "room is not OPEN")

    studio = db.studios[contract["studio_id"]]
    windows = _occurrence_windows(contract, studio)

    # Lockout overlap: no occurrence window may collide with any CONFIRMED/
    # IN_SESSION booking on the room. Closed-interval day boundaries, no
    # turnaround buffer between same-contract occurrences (PRD §3.8).
    for (occ_start, occ_end) in windows:
        for other in db.bookings.values():
            if other["room_id"] != contract["room_id"]:
                continue
            if other["schedule_status"] not in ("CONFIRMED", "IN_SESSION"):
                continue
            o_start, o_end = bl.booking_window(other)
            if bl.intervals_overlap(occ_start, occ_end, o_start, o_end):
                raise err("ERR_LOCKOUT_CONFLICT", "occurrence window collides with an existing booking")

    # Materialize: lock room, create anchor + occurrence bookings.
    room["status"] = "LOCKED"
    touch(room)

    anchor = _materialize_anchor(contract, room)

    count = 0
    for (occ_start, occ_end) in windows:
        _materialize_occurrence(contract, room, anchor, occ_start, occ_end)
        count += 1

    contract["occurrences_generated"] = count
    contract["status"] = "ACTIVE"
    touch(contract)
    return success_object(public(contract))


def _materialize_anchor(contract, room):
    """Create the series anchor booking (is_series_anchor=true, LOCKOUT)."""
    # Anchor spans the full window so it has a defined schedule window.
    start_dt = parse_iso(contract["window_start_date"])
    end_dt = parse_iso(contract["window_end_date"])
    if not (end_dt > start_dt):
        # Single-day window: give the anchor a 1-second positive duration so
        # its window is well-formed. Anchor is not part of the calendar checks.
        end_dt = end_dt + timedelta(seconds=1)
    base_charge = calc.base_charge_cents("LOCKOUT", start_dt, end_dt, room)
    studio = db.studios[contract["studio_id"]]
    deposit_due = calc.deposit_due_cents(base_charge, studio["deposit_pct"])
    anchor = {
        "studio_id": contract["studio_id"],
        "room_id": contract["room_id"],
        "client_id": contract["client_id"],
        "parent_series_id": None,
        "booking_kind": "LOCKOUT",
        "is_series_anchor": True,
        "start_at": db_iso(start_dt),
        "end_at": db_iso(end_dt),
        "actual_end_at": None,
        "schedule_status": "HELD",
        "settlement_status": "AWAITING_DEPOSIT",
        "base_charge_cents": base_charge,
        "deposit_due_cents": deposit_due,
        "overtime_cents": 0,
        "total_charge_cents": 0,
        "amount_paid_cents": 0,
        "hold_expires_at": None,
        "_contract_id": contract["id"],
    }
    stamp_common(anchor)
    db.bookings[anchor["id"]] = anchor
    return anchor


def _materialize_occurrence(contract, room, anchor, occ_start, occ_end):
    """Create one occurrence booking, CONFIRMED + DEPOSIT_PAID (PRD §3.8)."""
    studio = db.studios[contract["studio_id"]]
    base_charge = calc.base_charge_cents("LOCKOUT", occ_start, occ_end, room)
    deposit_due = calc.deposit_due_cents(base_charge, studio["deposit_pct"])
    occ = {
        "studio_id": contract["studio_id"],
        "room_id": contract["room_id"],
        "client_id": contract["client_id"],
        "parent_series_id": anchor["id"],
        "booking_kind": "LOCKOUT",
        "is_series_anchor": False,
        "start_at": db_iso(occ_start),
        "end_at": db_iso(occ_end),
        "actual_end_at": None,
        "schedule_status": "CONFIRMED",
        "settlement_status": "DEPOSIT_PAID",
        "base_charge_cents": base_charge,
        "deposit_due_cents": deposit_due,
        "overtime_cents": 0,
        "total_charge_cents": 0,
        "amount_paid_cents": 0,
        "hold_expires_at": None,
        "_contract_id": contract["id"],
    }
    stamp_common(occ)
    db.bookings[occ["id"]] = occ
    return occ


@bp.route("/studio/lockout-contracts/<cid>/terminate", methods=["POST"])
def terminate_contract(cid):
    principal = get_principal()
    require_roles(principal, {"StudioManager"})
    contract = get_or_404(db.lockout_contracts, cid, "lockout contract")

    if contract["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "contract is not ACTIVE")

    room = db.rooms[contract["room_id"]]
    room["status"] = "OPEN"
    touch(room)

    studio = db.studios[contract["studio_id"]]
    now = clock_now()

    # Cancel every future occurrence (start_at > now), CONFIRMED -> CANCELLED,
    # cascading child releases transitively (PRD §3.8). Occurrences (not the
    # anchor) carry this contract's id via _contract_id.
    for booking in list(db.bookings.values()):
        if booking.get("_contract_id") != contract["id"]:
            continue
        if booking.get("parent_series_id") is None:
            # the anchor itself — not a calendar occurrence to cancel
            continue
        if booking["schedule_status"] != "CONFIRMED":
            continue
        start_at = parse_iso(booking["start_at"])
        if start_at > now:
            bl.perform_cancellation(booking, studio, booking["client_id"])

    contract["status"] = "TERMINATED"
    touch(contract)
    return success_object(public(contract))
