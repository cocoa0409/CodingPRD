"""Reservation routes — booking, walk-in, check-in, cancel."""

from datetime import timedelta

from flask import Blueprint, g, request

from db import DB, new_id
from errors import (
    ERR_FORBIDDEN,
    ERR_INCOMPATIBLE_MODEL,
    ERR_INVALID_INPUT,
    ERR_INVALID_STATE,
    ERR_INVALID_TIME_SLOT,
    ERR_MEMBER_BLOCKED,
    ERR_NO_COMPATIBLE_BATTERY,
    ERR_RESERVATION_OVERLAP_MEMBER,
    ERR_STATION_CAPACITY_FULL,
    raise_error,
)
from middleware import auth_required
from response import list_response, success_response
from services.audit import append_audit
from services.calculations import compute_swap_billing
from services.common import (
    bump_version,
    check_occ,
    get_body,
    get_or_404,
    get_pagination,
    init_common,
    paginate,
    require_string,
    sort_by_created_at_asc,
)
from services.lookups import (
    battery_model_by_code,
    charging_slot_for_battery,
    is_compatible,
)
from services.time_util import format_iso, parse_iso, server_now


bp = Blueprint("reservations", __name__, url_prefix="/swap-stations")


RESERVATION_STATUSES = {"BOOKED", "CHECKED_IN", "FULFILLED", "CANCELLED", "NO_SHOW"}


# ---------------------------------------------------------------------------
# Eligibility filter and ranking for the held battery
# ---------------------------------------------------------------------------

def _pick_held_battery(*, station_id, vehicle_model_code, exclude_held_ids):
    """Return the highest-ranked eligible IDLE battery id, or None."""
    candidates = []
    for b in DB["batteries"].values():
        if b.get("status") != "IDLE":
            continue
        if b.get("station_id") != station_id:
            continue
        if b.get("recall_flag"):
            continue
        if b["id"] in exclude_held_ids:
            continue
        if not is_compatible(vehicle_model_code, b.get("battery_model_code")):
            continue
        candidates.append(b)
    if not candidates:
        return None
    candidates.sort(key=lambda b: (
        -float(b.get("soh_pct", 0.0)),
        int(b.get("cycle_count", 0)),
        b.get("created_at", ""),
        b.get("id", ""),
    ))
    return candidates[0]


def _currently_held_battery_ids():
    """Battery ids currently soft-held by a BOOKED reservation."""
    held = set()
    for r in DB["reservations"].values():
        if r.get("status") == "BOOKED" and r.get("held_battery_id"):
            held.add(r["held_battery_id"])
    return held


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open intervals overlap iff they share an interior instant."""
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------------------
# Member scoping helper
# ---------------------------------------------------------------------------

def _enforce_member_scope_create(member_id: str) -> None:
    if g.user_role == "Member" and g.user_id != member_id:
        raise_error(ERR_FORBIDDEN, "Member can only act on own reservations")


# ---------------------------------------------------------------------------
# POST /reservations
# ---------------------------------------------------------------------------

@bp.route("/reservations", methods=["POST"])
@auth_required(["Member", "StationOperator"])
def create_reservation():
    body = get_body()
    member_id = require_string(body, "member_id")
    vehicle_id = require_string(body, "vehicle_id")
    station_id = require_string(body, "station_id")
    slot_start_at = require_string(body, "slot_start_at")
    slot_end_at = require_string(body, "slot_end_at")

    _enforce_member_scope_create(member_id)

    # Existence checks
    member = DB["members"].get(member_id)
    if member is None:
        raise_error(ERR_INVALID_INPUT, "member_id does not exist")
    vehicle = DB["vehicles"].get(vehicle_id)
    if vehicle is None:
        raise_error(ERR_INVALID_INPUT, "vehicle_id does not exist")
    station = DB["stations"].get(station_id)
    if station is None:
        raise_error(ERR_INVALID_INPUT, "station_id does not exist")

    start_dt = parse_iso(slot_start_at)
    end_dt = parse_iso(slot_end_at)
    if start_dt is None or end_dt is None:
        raise_error(ERR_INVALID_INPUT, "slot_start_at/slot_end_at must be ISO 8601")

    # Validation 8: slot length must be exactly 15 minutes
    if end_dt - start_dt != timedelta(minutes=15):
        raise_error(ERR_INVALID_TIME_SLOT, "Reservation slot must be exactly 15 minutes")

    # Validation 9: slot_start_at >= now + 5 minutes
    now = server_now()
    if start_dt < now + timedelta(minutes=5):
        raise_error(ERR_INVALID_TIME_SLOT, "Reservation slot_start_at must be at least 5 minutes in the future")

    # Validation 10: per-member half-open overlap
    for r in DB["reservations"].values():
        if r.get("status") != "BOOKED":
            continue
        if r.get("member_id") != member_id:
            continue
        existing_start = parse_iso(r["slot_start_at"])
        existing_end = parse_iso(r["slot_end_at"])
        if existing_start is None or existing_end is None:
            continue
        if _intervals_overlap(start_dt, end_dt, existing_start, existing_end):
            raise_error(ERR_RESERVATION_OVERLAP_MEMBER,
                        "Member has an overlapping BOOKED reservation")

    # Validation 11: station capacity — strict overlap
    strict_overlap_count = 0
    for r in DB["reservations"].values():
        if r.get("status") != "BOOKED":
            continue
        if r.get("station_id") != station_id:
            continue
        existing_start = parse_iso(r["slot_start_at"])
        existing_end = parse_iso(r["slot_end_at"])
        if existing_start is None or existing_end is None:
            continue
        if _intervals_overlap(start_dt, end_dt, existing_start, existing_end):
            strict_overlap_count += 1
    if strict_overlap_count + 1 > int(station["total_slots"]):
        raise_error(ERR_STATION_CAPACITY_FULL, "Station capacity full at requested instant")

    # Validation 12: at least one eligible IDLE battery
    held_ids = _currently_held_battery_ids()
    picked = _pick_held_battery(
        station_id=station_id,
        vehicle_model_code=vehicle["vehicle_model_code"],
        exclude_held_ids=held_ids,
    )
    if picked is None:
        raise_error(ERR_NO_COMPATIBLE_BATTERY, "No eligible IDLE battery available")

    # Validation 13: member not blocked
    blocked_until = member.get("reservation_blocked_until")
    if blocked_until:
        blk_dt = parse_iso(blocked_until)
        if blk_dt is not None and blk_dt > now:
            raise_error(ERR_MEMBER_BLOCKED, "Member is temporarily blocked from reservations")

    row = {
        "id": new_id(),
        "member_id": member_id,
        "vehicle_id": vehicle_id,
        "station_id": station_id,
        "slot_start_at": format_iso(start_dt),
        "slot_end_at": format_iso(end_dt),
        "status": "BOOKED",
        "held_battery_id": picked["id"],
        "queue_position": None,
    }
    init_common(row)
    DB["reservations"][row["id"]] = row
    append_audit("RESERVATION_CHANGE", "Reservation", row["id"], None, "BOOKED")
    return success_response(row, http_status=201)


# ---------------------------------------------------------------------------
# POST /reservations/walk-in
# ---------------------------------------------------------------------------

@bp.route("/reservations/walk-in", methods=["POST"])
@auth_required(["StationOperator"])
def create_walkin():
    body = get_body()
    member_id = require_string(body, "member_id")
    vehicle_id = require_string(body, "vehicle_id")
    station_id = require_string(body, "station_id")

    member = DB["members"].get(member_id)
    if member is None:
        raise_error(ERR_INVALID_INPUT, "member_id does not exist")
    vehicle = DB["vehicles"].get(vehicle_id)
    if vehicle is None:
        raise_error(ERR_INVALID_INPUT, "vehicle_id does not exist")
    station = DB["stations"].get(station_id)
    if station is None:
        raise_error(ERR_INVALID_INPUT, "station_id does not exist")

    now = server_now()

    # queue position: 1 + count of BOOKED+CHECKED_IN walk-ins at this station
    walkin_count = 0
    for r in DB["reservations"].values():
        if r.get("station_id") != station_id:
            continue
        if r.get("queue_position") is None:
            continue
        if r.get("status") in {"BOOKED", "CHECKED_IN"}:
            walkin_count += 1
    queue_position = walkin_count + 1

    start_dt = now + timedelta(minutes=5 * queue_position)
    end_dt = start_dt + timedelta(minutes=15)

    held_ids = _currently_held_battery_ids()
    picked = _pick_held_battery(
        station_id=station_id,
        vehicle_model_code=vehicle["vehicle_model_code"],
        exclude_held_ids=held_ids,
    )
    if picked is None:
        raise_error(ERR_NO_COMPATIBLE_BATTERY, "No eligible IDLE battery available")

    row = {
        "id": new_id(),
        "member_id": member_id,
        "vehicle_id": vehicle_id,
        "station_id": station_id,
        "slot_start_at": format_iso(start_dt),
        "slot_end_at": format_iso(end_dt),
        "status": "BOOKED",
        "held_battery_id": picked["id"],
        "queue_position": queue_position,
    }
    init_common(row)
    DB["reservations"][row["id"]] = row
    append_audit("RESERVATION_CHANGE", "Reservation", row["id"], None, "BOOKED")
    return success_response(row, http_status=201)


# ---------------------------------------------------------------------------
# GET /reservations and GET /reservations/{id}
# ---------------------------------------------------------------------------

@bp.route("/reservations", methods=["GET"])
@auth_required(["Member", "StationOperator", "PlatformAdmin"])
def list_reservations():
    limit, offset = get_pagination()
    member_id = request.args.get("member_id")
    station_id = request.args.get("station_id")
    status = request.args.get("status")
    if status is not None and status not in RESERVATION_STATUSES:
        raise_error(ERR_INVALID_INPUT, "Unknown reservation status filter")

    items = list(DB["reservations"].values())
    if g.user_role == "Member":
        items = [r for r in items if r.get("member_id") == g.user_id]
    elif g.user_role == "StationOperator":
        items = [r for r in items if r.get("station_id") == g.user_id]
    if member_id is not None:
        items = [r for r in items if r.get("member_id") == member_id]
    if station_id is not None:
        items = [r for r in items if r.get("station_id") == station_id]
    if status is not None:
        items = [r for r in items if r.get("status") == status]
    items = sort_by_created_at_asc(items)
    sliced, total = paginate(items, limit, offset)
    return list_response(sliced, total, limit, offset)


@bp.route("/reservations/<reservation_id>", methods=["GET"])
@auth_required(["Member", "StationOperator", "PlatformAdmin"])
def get_reservation(reservation_id):
    row = get_or_404("reservations", reservation_id)
    return success_response(row)


# ---------------------------------------------------------------------------
# POST /reservations/{id}/check-in
# ---------------------------------------------------------------------------

@bp.route("/reservations/<reservation_id>/check-in", methods=["POST"])
@auth_required(["StationOperator"])
def check_in(reservation_id):
    reservation = get_or_404("reservations", reservation_id)
    body = get_body()
    check_occ(reservation, body)

    if reservation.get("status") != "BOOKED":
        raise_error(ERR_INVALID_STATE, "Reservation is not BOOKED")

    start_dt = parse_iso(reservation["slot_start_at"])
    end_dt = parse_iso(reservation["slot_end_at"])
    now = server_now()
    if start_dt is None or end_dt is None or not (start_dt <= now < end_dt):
        raise_error(ERR_INVALID_STATE, "Current time is outside the reservation window")

    held_battery_id = reservation.get("held_battery_id")
    held_battery = DB["batteries"].get(held_battery_id) if held_battery_id else None
    if held_battery is None or held_battery.get("status") != "IDLE":
        raise_error(ERR_INVALID_STATE, "Held battery is no longer IDLE")

    vehicle = DB["vehicles"].get(reservation["vehicle_id"])
    if vehicle is None:
        raise_error(ERR_INVALID_STATE, "Vehicle missing")
    if not is_compatible(vehicle["vehicle_model_code"], held_battery["battery_model_code"]):
        raise_error(ERR_INCOMPATIBLE_MODEL, "Compatibility no longer satisfied")

    prev_status = reservation["status"]
    reservation["status"] = "CHECKED_IN"
    bump_version(reservation)

    # Create the swap event row.
    swap_event = {
        "id": new_id(),
        "reservation_id": reservation_id,
        "vehicle_id": vehicle["id"],
        "station_id": reservation["station_id"],
        "outgoing_battery_id": vehicle.get("installed_battery_id"),
        "incoming_battery_id": None,
        "outgoing_soc_pct": None,
        "incoming_soc_pct": None,
        "phase": "CHECKED_IN",
        "provisional_total_cents": 0,
        "final_total_cents": 0,
        "completed_at": None,
    }
    init_common(swap_event)
    DB["swap_events"][swap_event["id"]] = swap_event

    # Provisional billing — uses held battery's current soc_pct.
    bm = battery_model_by_code(held_battery["battery_model_code"])
    rated_kwh = bm["rated_capacity_kwh"] if bm else 0.0

    slot = charging_slot_for_battery(held_battery["id"])
    tou_zone = slot["tou_zone"] if slot else "SHOULDER"
    # The held battery is IDLE — it isn't in a slot. Fall back to "SHOULDER"
    # for provisional pricing since the slot the battery came from is implicit.

    outgoing_battery = DB["batteries"].get(vehicle.get("installed_battery_id"))
    outgoing_soc = outgoing_battery.get("soc_pct", 0.0) if outgoing_battery else 0.0
    incoming_soc = held_battery.get("soc_pct", 0.0)

    member = DB["members"].get(reservation["member_id"])
    sub_tier = member.get("subscription_tier", "NONE") if member else "NONE"
    sub_remaining = member.get("subscription_swaps_remaining", 0) if member else 0

    provisional = compute_swap_billing(
        outgoing_soc_pct=outgoing_soc,
        incoming_soc_pct=incoming_soc,
        rated_capacity_kwh=rated_kwh,
        tou_zone=tou_zone,
        subscription_tier=sub_tier,
        subscription_swaps_remaining=sub_remaining,
    )
    swap_event["provisional_total_cents"] = int(provisional["amount_due_cents"])
    bump_version(swap_event)

    # Denormalise swap_event identification onto the reservation row in
    # the response so the workflow caller can reach the freshly-created
    # SwapEvent (PRD §3.4: "a fresh SwapEvent is created with phase set
    # to CHECKED_IN"). The only retrieval endpoint exposed by PRD is
    # GET /swap-events/{id}; surfacing the id here is the only way a
    # caller can reach the SwapEvent at all after check-in.
    reservation["swap_event_id"] = swap_event["id"]

    append_audit("RESERVATION_CHANGE", "Reservation", reservation_id, prev_status, "CHECKED_IN")
    append_audit("SWAP_PHASE_CHANGE", "SwapEvent", swap_event["id"], None, "CHECKED_IN")
    return success_response(reservation)


# ---------------------------------------------------------------------------
# POST /reservations/{id}/cancel
# ---------------------------------------------------------------------------

@bp.route("/reservations/<reservation_id>/cancel", methods=["POST"])
@auth_required(["Member", "StationOperator"])
def cancel_reservation(reservation_id):
    reservation = get_or_404("reservations", reservation_id)
    body = get_body()
    check_occ(reservation, body)

    # Member can only cancel own; StationOperator can only cancel at own station.
    if g.user_role == "Member" and reservation.get("member_id") != g.user_id:
        raise_error(ERR_FORBIDDEN, "Member can only cancel own reservation")
    if g.user_role == "StationOperator" and reservation.get("station_id") != g.user_id:
        raise_error(ERR_FORBIDDEN, "StationOperator can only cancel at own station")

    if reservation.get("status") != "BOOKED":
        raise_error(ERR_INVALID_STATE, "Reservation is not BOOKED")

    start_dt = parse_iso(reservation["slot_start_at"])
    now = server_now()
    if start_dt is None or now > start_dt - timedelta(minutes=5):
        raise_error(ERR_INVALID_STATE, "Cancellation window has closed")

    prev = reservation["status"]
    reservation["status"] = "CANCELLED"
    reservation["held_battery_id"] = None
    bump_version(reservation)
    append_audit("RESERVATION_CHANGE", "Reservation", reservation_id, prev, "CANCELLED")
    return success_response(reservation)
