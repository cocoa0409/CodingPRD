"""Ledgers (PRD 2.10), interval semantics (PRD 2.9) and cascades (PRD 2.12)."""

from datetime import timedelta
from decimal import Decimal

import calc
import store
from constants import (MIN_USABLE_BOARD_FEET, QUARANTINE_AFTER_HOURS,
                       REWORK_ESCALATION_THRESHOLD, REWORK_SLIP_DAYS)
from store import touch

TERMINAL_RUN = ("COMPLETED", "REJECTED")
BUSY_RUN = ("SPRAYING", "CURING", "CURE_SUSPENDED", "BUFFING")


# ------------------------------------------------------------ wood ledger -----

def lot_move(lot, src, dst, amount):
    amount = calc.bf(amount)
    lot[src] = calc.bf(Decimal(lot[src]) - amount)
    lot[dst] = calc.bf(Decimal(lot[dst]) + amount)


def lot_after_cut(lot, board_feet, kerf):
    lot["board_feet_available"] = calc.bf(
        Decimal(lot["board_feet_available"]) - Decimal(board_feet) - Decimal(kerf))
    lot["board_feet_unassigned"] = calc.bf(
        Decimal(lot["board_feet_unassigned"]) + Decimal(board_feet))
    lot["board_feet_kerf_loss"] = calc.bf(
        Decimal(lot["board_feet_kerf_loss"]) + Decimal(kerf))
    if (lot["status"] == "RELEASED"
            and Decimal(lot["board_feet_available"]) < MIN_USABLE_BOARD_FEET):
        lot["status"] = "DEPLETED"
    touch(lot)


def reserve_billet(billet):
    """POST /components: the billet is committed to a part."""
    lot = store.LOTS.get(billet["lot_id"])
    billet["status"] = "RESERVED"
    touch(billet)
    if lot is not None:
        lot_move(lot, "board_feet_unassigned", "board_feet_reserved",
                 billet["board_feet"])
        touch(lot)


def consume_billet(billet):
    lot = store.LOTS.get(billet["lot_id"])
    billet["status"] = "CONSUMED"
    touch(billet)
    if lot is not None:
        lot_move(lot, "board_feet_reserved", "board_feet_consumed",
                 billet["board_feet"])
        touch(lot)


def scrap_billet(billet):
    """QC scrap DESTROYS the wood: reserved -> scrapped."""
    lot = store.LOTS.get(billet["lot_id"])
    billet["status"] = "SCRAPPED"
    touch(billet)
    if lot is not None:
        lot_move(lot, "board_feet_reserved", "board_feet_scrapped",
                 billet["board_feet"])
        touch(lot)


def recover_billet(billet):
    """Cancellation RECOVERS the wood: reserved -> unassigned."""
    lot = store.LOTS.get(billet["lot_id"])
    billet["status"] = "AVAILABLE"
    touch(billet)
    if lot is not None:
        lot_move(lot, "board_feet_reserved", "board_feet_unassigned",
                 billet["board_feet"])
        touch(lot)


# --------------------------------------------------------- station minutes ----

def station_book(station, minutes):
    station["total_scheduled_minutes"] += minutes
    station["held_minutes"] += minutes
    touch(station)


def station_consume(station, minutes):
    station["held_minutes"] -= minutes
    station["consumed_minutes"] += minutes
    touch(station)


def station_release(station, minutes):
    station["held_minutes"] -= minutes
    station["released_minutes"] += minutes
    touch(station)


def release_reservation(res):
    if res["status"] != "HELD":
        return
    res["status"] = "RELEASED"
    touch(res)
    station = store.STATIONS.get(res["station_id"])
    if station is not None:
        station_release(station, res["duration_minutes"])


# -------------------------------------------------------- interval overlap ----

def station_conflict(station, starts_at, ends_at):
    """Half-open windows widened symmetrically by changeover_minutes.  Touching
    exactly at r.ends_at + changeover is accepted."""
    buffer = timedelta(minutes=station["changeover_minutes"])
    for res in store.RESERVATIONS.values():
        if res["station_id"] != station["id"]:
            continue
        if res["status"] not in ("HELD", "CONSUMED"):
            continue
        if starts_at < res["ends_at"] + buffer and ends_at + buffer > res["starts_at"]:
            return res
    return None


def booth_overlaps(booth_id, hold_from, hold_until):
    """Closed windows, no buffer: touching exactly at r.booth_hold_until
    collides."""
    out = []
    for run in store.RUNS.values():
        if run["booth_id"] != booth_id or run["status"] in TERMINAL_RUN:
            continue
        if hold_from <= run["booth_hold_until"] and hold_until >= run["booth_hold_from"]:
            out.append(run)
    return out


# ------------------------------------------------------- climate cascade ------

def climate_in_band(room, rh_pct):
    return abs(Decimal(rh_pct) - Decimal(room["target_rh_pct"])) \
        <= Decimal(room["rh_tolerance_pct"])


def record_climate_reading(room, rh_pct, temp_c):
    now = store.now_utc()
    room["latest_rh_pct"] = rh_pct
    room["latest_temp_c"] = temp_c
    room["last_reading_at"] = now
    in_band = climate_in_band(room, rh_pct)
    status = room["climate_status"]

    if status == "IN_SPEC":
        if not in_band:
            room["climate_status"] = "OUT_OF_SPEC"
            room["out_of_spec_since"] = now
            touch(room)
            _excursion_cascade(room, now)
            return room
    elif status == "OUT_OF_SPEC":
        if in_band:
            room["climate_status"] = "IN_SPEC"
            room["out_of_spec_since"] = None
        else:
            since = room["out_of_spec_since"]
            elapsed = (now - since).total_seconds() if since else 0
            if elapsed >= QUARANTINE_AFTER_HOURS * 3600:
                room["climate_status"] = "QUARANTINED"
                touch(room)
                _void_conditioning(room)
                return room
    touch(room)
    return room


def _excursion_cascade(room, now):
    """Depth 4: room -> curing runs -> owning orders -> future held holds."""
    orders = []
    for run in store.RUNS.values():
        if run["booth_id"] != room["id"] or run["status"] != "CURING":
            continue
        run["status"] = "CURE_SUSPENDED"
        run["cure_suspend_started_at"] = now
        touch(run)
        order = store.ORDERS.get(run["build_order_id"])
        if order is not None and order["build_stage"] == "IN_FINISH":
            order["build_stage"] = "FINISH_HELD"
            touch(order)
            orders.append(order)
    for order in orders:
        for res in list(store.RESERVATIONS.values()):
            if res["build_order_id"] != order["id"] or res["status"] != "HELD":
                continue
            if res["starts_at"] > now:
                release_reservation(res)


def _void_conditioning(room):
    for lot in store.LOTS.values():
        if lot["storage_room_id"] == room["id"] and lot["status"] == "CONDITIONED":
            lot["status"] = "RECEIVED"
            touch(lot)


# ---------------------------------------------------- lot rejection cascade ---

def reject_lot_cascade(lot):
    """Depth 4: lot -> billets -> components -> owning orders."""
    remaining = Decimal(lot["board_feet_available"])
    if remaining > 0:
        lot_move(lot, "board_feet_available", "board_feet_scrapped", remaining)

    touched_components = []
    for billet in store.BILLETS.values():
        if billet["lot_id"] != lot["id"]:
            continue
        if billet["status"] not in ("AVAILABLE", "RESERVED"):
            continue
        source = ("board_feet_unassigned" if billet["status"] == "AVAILABLE"
                  else "board_feet_reserved")
        lot_move(lot, source, "board_feet_scrapped", billet["board_feet"])
        billet["status"] = "QUARANTINED"
        touch(billet)
        for comp in store.COMPONENTS.values():
            if comp["billet_id"] != billet["id"]:
                continue
            if comp["status"] in ("INSTALLED", "SCRAPPED"):
                continue
            comp["status"] = "QC_HELD"
            comp["qc_hold_reason"] = "PROTECTED_SPECIES"
            touch(comp)
            touched_components.append(comp)

    for comp in touched_components:
        order = store.ORDERS.get(comp["build_order_id"]) \
            if comp["build_order_id"] else None
        if order is None:
            continue
        if order["build_stage"] in ("SERIALIZED", "SCRAPPED", "COMPLIANCE_HOLD"):
            continue
        order["stage_before_compliance_hold"] = order["build_stage"]
        order["build_stage"] = "COMPLIANCE_HOLD"
        touch(order)


# --------------------------------------------------- inspection fail cascade --

def inspection_fail_cascade(order):
    """Depth 3: round -> order back to SETUP -> commercial escalation."""
    order["build_stage"] = "SETUP"
    order["rework_round_count"] += 1
    if order["rework_round_count"] >= REWORK_ESCALATION_THRESHOLD:
        # The escalation is guarded only by the round count, so a third failure
        # slips the promise again even though the status move is already spent.
        if order["commercial_status"] in ("CONFIRMED", "OPTIONS_LOCKED"):
            order["commercial_status"] = "AT_RISK"
        order["promised_date"] = order["promised_date"] + timedelta(
            days=REWORK_SLIP_DAYS)
        calc.refresh_priority(order)
    touch(order)


# --------------------------------------------------------- order helpers ------

def order_components(order):
    return [c for c in store.COMPONENTS.values()
            if c["build_order_id"] == order["id"]]
