"""SwapEvent routes — inspect, uninstall, install, complete, abort."""

from flask import Blueprint

from db import DB, new_id
from errors import (
    ERR_BATTERY_RECALLED,
    ERR_INCOMPATIBLE_MODEL,
    ERR_INVALID_INPUT,
    ERR_INVALID_STATE,
    raise_error,
)
from middleware import auth_required
from response import success_response
from services.audit import append_audit
from services.calculations import compute_swap_billing
from services.common import (
    bump_version,
    check_occ,
    get_body,
    get_or_404,
    init_common,
    require_bool,
    require_number,
)
from services.lookups import (
    battery_model_by_code,
    charging_slot_for_battery,
    is_compatible,
)
from services.time_util import format_iso, server_now


bp = Blueprint("swap_events", __name__, url_prefix="/swap-stations")


@bp.route("/swap-events/<swap_id>", methods=["GET"])
@auth_required(["StationOperator", "PlatformAdmin", "Member"])
def get_swap_event(swap_id):
    row = get_or_404("swap_events", swap_id)
    return success_response(row)


# ---------------- inspect ---------------------------------------------------

@bp.route("/swap-events/<swap_id>/inspect", methods=["POST"])
@auth_required(["StationOperator"])
def inspect(swap_id):
    swap = get_or_404("swap_events", swap_id)
    body = get_body()
    check_occ(swap, body)

    if swap.get("phase") != "CHECKED_IN":
        raise_error(ERR_INVALID_STATE, "SwapEvent phase must be CHECKED_IN")

    outgoing_soc = require_number(body, "outgoing_soc_pct")
    if not (0.0 <= outgoing_soc <= 100.0):
        raise_error(ERR_INVALID_INPUT, "outgoing_soc_pct must be in [0, 100]")

    prev = swap["phase"]
    swap["outgoing_soc_pct"] = float(outgoing_soc)
    swap["phase"] = "INSPECTED"
    bump_version(swap)
    append_audit("SWAP_PHASE_CHANGE", "SwapEvent", swap_id, prev, "INSPECTED")
    return success_response(swap)


# ---------------- uninstall -------------------------------------------------

@bp.route("/swap-events/<swap_id>/uninstall", methods=["POST"])
@auth_required(["StationOperator"])
def uninstall(swap_id):
    swap = get_or_404("swap_events", swap_id)
    body = get_body()
    check_occ(swap, body)

    if swap.get("phase") != "INSPECTED":
        raise_error(ERR_INVALID_STATE, "SwapEvent phase must be INSPECTED")

    outgoing_battery_id = swap.get("outgoing_battery_id")
    outgoing_battery = DB["batteries"].get(outgoing_battery_id) if outgoing_battery_id else None
    vehicle = DB["vehicles"].get(swap["vehicle_id"])
    station = DB["stations"].get(swap["station_id"])

    if outgoing_battery is not None:
        prev_status = outgoing_battery["status"]
        outgoing_battery["status"] = "IDLE"
        outgoing_battery["station_id"] = swap["station_id"]
        if swap.get("outgoing_soc_pct") is not None:
            outgoing_battery["soc_pct"] = float(swap["outgoing_soc_pct"])
        bump_version(outgoing_battery)
        append_audit("BATTERY_STATUS_CHANGE", "Battery", outgoing_battery_id,
                     prev_status, "IDLE")
        if station is not None:
            station["idle_battery_count"] = int(station.get("idle_battery_count", 0)) + 1
            bump_version(station)

    if vehicle is not None:
        vehicle["installed_battery_id"] = None
        bump_version(vehicle)

    prev_phase = swap["phase"]
    swap["phase"] = "UNINSTALLED"
    bump_version(swap)
    append_audit("SWAP_PHASE_CHANGE", "SwapEvent", swap_id, prev_phase, "UNINSTALLED")
    return success_response(swap)


# ---------------- install ---------------------------------------------------

@bp.route("/swap-events/<swap_id>/install", methods=["POST"])
@auth_required(["StationOperator"])
def install(swap_id):
    swap = get_or_404("swap_events", swap_id)
    body = get_body()
    check_occ(swap, body)

    if swap.get("phase") != "UNINSTALLED":
        raise_error(ERR_INVALID_STATE, "SwapEvent phase must be UNINSTALLED")

    verify = require_bool(body, "verify")
    if not verify:
        raise_error(ERR_INVALID_INPUT, "verify must be true (BMS handshake passed)")

    reservation = DB["reservations"].get(swap["reservation_id"])
    if reservation is None:
        raise_error(ERR_INVALID_STATE, "Reservation missing")
    held_id = reservation.get("held_battery_id")
    held_battery = DB["batteries"].get(held_id) if held_id else None
    if held_battery is None or held_battery.get("status") != "IDLE":
        raise_error(ERR_INVALID_STATE, "Held battery is no longer IDLE")
    if held_battery.get("recall_flag"):
        raise_error(ERR_BATTERY_RECALLED, "Held battery has been recalled")

    vehicle = DB["vehicles"].get(swap["vehicle_id"])
    if vehicle is None:
        raise_error(ERR_INVALID_STATE, "Vehicle missing")
    if not is_compatible(vehicle["vehicle_model_code"], held_battery["battery_model_code"]):
        raise_error(ERR_INCOMPATIBLE_MODEL, "Compatibility no longer satisfied")

    # Side effects
    prev_status = held_battery["status"]
    held_battery["status"] = "IN_USE"
    bump_version(held_battery)
    vehicle["installed_battery_id"] = held_battery["id"]
    bump_version(vehicle)

    station = DB["stations"].get(swap["station_id"])
    if station is not None:
        station["idle_battery_count"] = max(0, int(station.get("idle_battery_count", 0)) - 1)
        bump_version(station)

    swap["incoming_battery_id"] = held_battery["id"]
    swap["incoming_soc_pct"] = float(held_battery.get("soc_pct", 0.0))
    prev_phase = swap["phase"]
    swap["phase"] = "INSTALLED"
    bump_version(swap)

    append_audit("BATTERY_STATUS_CHANGE", "Battery", held_battery["id"], prev_status, "IN_USE")
    append_audit("SWAP_PHASE_CHANGE", "SwapEvent", swap_id, prev_phase, "INSTALLED")
    return success_response(swap)


# ---------------- complete --------------------------------------------------

@bp.route("/swap-events/<swap_id>/complete", methods=["POST"])
@auth_required(["StationOperator"])
def complete(swap_id):
    swap = get_or_404("swap_events", swap_id)
    body = get_body()
    check_occ(swap, body)

    if swap.get("phase") != "INSTALLED":
        raise_error(ERR_INVALID_STATE, "SwapEvent phase must be INSTALLED")

    reservation = DB["reservations"].get(swap["reservation_id"])
    member = DB["members"].get(reservation["member_id"]) if reservation else None
    held_battery = DB["batteries"].get(swap.get("incoming_battery_id"))
    bm = battery_model_by_code(held_battery["battery_model_code"]) if held_battery else None
    rated_kwh = bm["rated_capacity_kwh"] if bm else 0.0

    # The tou_zone of the slot the incoming battery came from. By the time the
    # battery is installed the slot is empty and battery_id is cleared, so we
    # cannot trace back through the slot table. We fall back to SHOULDER for
    # final billing — consistent with the provisional calculation.
    tou_zone = "SHOULDER"

    outgoing_soc = float(swap.get("outgoing_soc_pct") or 0.0)
    incoming_soc = float(swap.get("incoming_soc_pct") or 0.0)
    sub_tier = member.get("subscription_tier", "NONE") if member else "NONE"
    sub_remaining = member.get("subscription_swaps_remaining", 0) if member else 0

    billing = compute_swap_billing(
        outgoing_soc_pct=outgoing_soc,
        incoming_soc_pct=incoming_soc,
        rated_capacity_kwh=rated_kwh,
        tou_zone=tou_zone,
        subscription_tier=sub_tier,
        subscription_swaps_remaining=sub_remaining,
    )

    swap["final_total_cents"] = int(billing["amount_due_cents"])
    prev_phase = swap["phase"]
    swap["phase"] = "COMPLETED"
    swap["completed_at"] = format_iso(server_now())
    bump_version(swap)

    # Decrement subscription credits if a deduction was applied (and credits remain).
    if member is not None and billing["subscription_deduction_cents"] > 0:
        if int(member.get("subscription_swaps_remaining", 0)) > 0:
            member["subscription_swaps_remaining"] = int(member["subscription_swaps_remaining"]) - 1
            bump_version(member)

    # Bubble the reservation up to FULFILLED.
    if reservation is not None:
        prev_res = reservation["status"]
        reservation["status"] = "FULFILLED"
        bump_version(reservation)
        append_audit("RESERVATION_CHANGE", "Reservation", reservation["id"],
                     prev_res, "FULFILLED")

    # Create BillingRecord.
    billing_row = {
        "id": new_id(),
        "swap_event_id": swap_id,
        "member_id": member["id"] if member else None,
        "per_swap_base_cents": int(billing["per_swap_base_cents"]),
        "soc_diff_cents": int(billing["soc_diff_cents"]),
        "tou_pass_through_cents": int(billing["tou_pass_through_cents"]),
        "subscription_deduction_cents": int(billing["subscription_deduction_cents"]),
        "amount_due_cents": int(billing["amount_due_cents"]),
        "payment_status": "PENDING",
        "refund_cents": 0,
    }
    init_common(billing_row)
    DB["billing_records"][billing_row["id"]] = billing_row

    append_audit("SWAP_PHASE_CHANGE", "SwapEvent", swap_id, prev_phase, "COMPLETED")
    return success_response(swap)


# ---------------- abort -----------------------------------------------------

@bp.route("/swap-events/<swap_id>/abort", methods=["POST"])
@auth_required(["StationOperator"])
def abort(swap_id):
    swap = get_or_404("swap_events", swap_id)
    body = get_body()
    check_occ(swap, body)

    if swap.get("phase") not in {"CHECKED_IN", "INSPECTED", "UNINSTALLED"}:
        raise_error(ERR_INVALID_STATE, "SwapEvent cannot be aborted from this phase")

    prev_phase = swap["phase"]

    # Compensating physical action if outgoing battery was already removed.
    if prev_phase == "UNINSTALLED":
        outgoing_id = swap.get("outgoing_battery_id")
        outgoing_battery = DB["batteries"].get(outgoing_id) if outgoing_id else None
        vehicle = DB["vehicles"].get(swap["vehicle_id"])
        station = DB["stations"].get(swap["station_id"])
        if outgoing_battery is not None:
            prev_b_status = outgoing_battery["status"]
            outgoing_battery["status"] = "IN_USE"
            bump_version(outgoing_battery)
            append_audit("BATTERY_STATUS_CHANGE", "Battery", outgoing_id,
                         prev_b_status, "IN_USE")
        if vehicle is not None:
            vehicle["installed_battery_id"] = outgoing_id
            bump_version(vehicle)
        if station is not None:
            station["idle_battery_count"] = max(
                0, int(station.get("idle_battery_count", 0)) - 1
            )
            bump_version(station)

    swap["phase"] = "ABORTED"
    bump_version(swap)
    append_audit("SWAP_PHASE_CHANGE", "SwapEvent", swap_id, prev_phase, "ABORTED")

    # Release the soft hold and cancel the reservation.
    reservation = DB["reservations"].get(swap["reservation_id"])
    if reservation is not None:
        prev_res = reservation["status"]
        reservation["status"] = "CANCELLED"
        reservation["held_battery_id"] = None
        bump_version(reservation)
        append_audit("RESERVATION_CHANGE", "Reservation", reservation["id"],
                     prev_res, "CANCELLED")
    return success_response(swap)
