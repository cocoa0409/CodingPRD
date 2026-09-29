"""Lookups, conserved ledgers and cascade helpers (PRD 2.9, 3.1, 3.3, 3.5)."""
from datetime import timedelta

import calc
import errors
from db import db, ordered, touch

OCCUPYING_CUSTODY = ("IN_COLD_STORAGE", "IN_VESSEL", "TREATED")
DECLARED_CUSTODY = ("AT_DOCK", "IN_COLD_STORAGE", "IN_VESSEL", "TREATED")
RESERVING_CYCLE_STATES = ("SCHEDULED", "LOADED", "RUNNING")
CONSUMING_LOAD_STATES = ("ALLOCATED", "REPROCESSED")
OCCUPYING_CYCLE_STATES = ("SCHEDULED", "LOADED", "RUNNING", "COMPLETED_CLEAN",
                          "COMPLETED_DEVIATED", "DISPOSITIONED")


# --------------------------------------------------------------------- lookups
def find(store, row_id, error_id):
    row = store.get(row_id)
    if row is None:
        raise errors.not_found(error_id)
    return row


def loads_of_cycle(cycle_id):
    return ordered([r for r in db.loads.values() if r["cycle_id"] == cycle_id])


def pending_loads(cycle_id):
    return [r for r in loads_of_cycle(cycle_id) if r["disposition_state"] == "PENDING"]


def live_loads(cycle_id):
    """Loads that still count toward basket occupancy (anything but VOIDED)."""
    return [r for r in loads_of_cycle(cycle_id) if r["disposition_state"] != "VOIDED"]


def loads_of_lot(lot_id):
    return ordered([r for r in db.loads.values() if r["lot_id"] == lot_id])


def latest_live_load_of_lot(lot_id):
    live = [r for r in loads_of_lot(lot_id) if r["disposition_state"] != "VOIDED"]
    return live[-1] if live else None


def lot_of(load):
    return db.lots.get(load["lot_id"])


def qualification_of(lot):
    return db.qualifications.get(lot["qualification_id"])


def family_of_qualification(qualification):
    if qualification is None:
        return None
    return db.product_families.get(qualification["product_family_id"])


def family_of_lot(lot):
    return family_of_qualification(qualification_of(lot))


def vessel_of(cycle):
    return db.vessels.get(cycle["vessel_id"])


def family_of_cycle(cycle):
    return db.product_families.get(cycle["product_family_id"])


def deviations_of_cycle(cycle_id):
    return ordered([r for r in db.deviations.values() if r["cycle_id"] == cycle_id])


def logs_of_cycle(cycle_id):
    return ordered([r for r in db.cycle_logs.values() if r["cycle_id"] == cycle_id])


def log_of_cycle(cycle_id):
    rows = logs_of_cycle(cycle_id)
    return rows[0] if rows else None


def runs_of_qualification(qualification_id):
    return ordered([r for r in db.validation_runs.values()
                    if r["qualification_id"] == qualification_id])


def customer_of_load(load):
    lot = lot_of(load)
    return lot["customer_id"] if lot else None


# ------------------------------------------------------- cold room (PRD 3.1)
def room_occupancy(room_id):
    return sum(1 for r in db.lots.values()
               if r["cold_room_id"] == room_id
               and r["custody_state"] in OCCUPYING_CUSTODY)


def posture(occupied, capacity):
    return "AT_CAPACITY" if occupied >= capacity else "NORMAL"


def recompute_room(room):
    """occupied_pallets is derived; version moves only when the posture flips."""
    if room is None:
        return
    occupied = room_occupancy(room["id"])
    room["occupied_pallets"] = occupied
    state = posture(occupied, room["capacity_pallets"])
    if state != room["capacity_state"]:
        room["capacity_state"] = state
        touch(room)


def room_of_lot(lot):
    return db.cold_rooms.get(lot["cold_room_id"])


def interval_occupancy_exceeded(room, start, end):
    """Declared occupancy over the closed candidate interval (PRD 3.4)."""
    population = [r for r in db.lots.values()
                  if r["cold_room_id"] == room["id"]
                  and r["custody_state"] in DECLARED_CUSTODY]
    points = [start]
    for row in population:
        if start <= row["created_at"] <= end:
            points.append(row["created_at"])
    for point in sorted(points):
        occupancy = 1 + sum(1 for row in population
                            if row["created_at"] <= point <= row["ship_by"])
        if occupancy > room["capacity_pallets"]:
            return True
    return False


# ------------------------------------------------- contract slot ledger (2.9)
def contract_ledger(contract):
    reserved = 0
    consumed = 0
    for load in db.loads.values():
        if load["contract_id"] != contract["id"]:
            continue
        if load["disposition_state"] == "PENDING":
            cycle = db.cycles.get(load["cycle_id"])
            if cycle is not None and cycle["state"] in RESERVING_CYCLE_STATES:
                reserved += 1
        elif load["disposition_state"] in CONSUMING_LOAD_STATES:
            consumed += 1
    return {
        "reserved_slots": reserved,
        "consumed_slots": consumed,
        "available_slots": contract["committed_slots"] - reserved - consumed,
    }


def recompute_contract(contract):
    """Recompute the ledger; ACTIVE <-> EXHAUSTED oscillates on the result."""
    if contract is None:
        return
    ledger = contract_ledger(contract)
    contract.update(ledger)
    if contract["status"] == "ACTIVE" and ledger["available_slots"] <= 0:
        contract["status"] = "EXHAUSTED"
        touch(contract)
    elif contract["status"] == "EXHAUSTED" and ledger["available_slots"] >= 1:
        contract["status"] = "ACTIVE"
        touch(contract)


def recompute_contracts_of(loads):
    seen = set()
    for load in loads:
        contract_id = load.get("contract_id")
        if contract_id in seen:
            continue
        seen.add(contract_id)
        recompute_contract(db.contracts.get(contract_id))


# --------------------------------------------- customer chargeback balance
def pending_balance(customer_id):
    return sum(r["amount_cents"] for r in db.chargeback_lines.values()
               if r["customer_id"] == customer_id and r["status"] == "PENDING")


def recompute_customer_balance(customer):
    if customer is None:
        return
    total = pending_balance(customer["id"])
    if customer["chargeback_balance_cents"] != total:
        customer["chargeback_balance_cents"] = total
        touch(customer)


# ------------------------------------------------------ lot unit ledger (2.9)
def move_units(lot, source, target, amount):
    amount = int(amount or 0)
    if amount <= 0:
        return
    lot[source] -= amount
    lot[target] += amount


# ------------------------------------------------------- cycle recomputations
def recompute_cycle_estimate(cycle):
    """ESTIMATED variant: baskets, utilisation, seconds, scheduled_end, fee."""
    vessel = vessel_of(cycle)
    total = sum(r["baskets_used"] for r in live_loads(cycle["id"]))
    cycle["baskets_used_total"] = total
    cycle["utilization_pct"] = calc.utilization_pct(total, vessel["basket_count"])
    seconds = calc.cycle_seconds(
        calc.estimated_come_up_seconds(cycle["target_pressure_mpa"],
                                       vessel["pump_ramp_rate_mpa_per_sec"]),
        cycle["target_hold_seconds"],
        vessel["decompression_seconds"])
    cycle["estimated_cycle_seconds"] = seconds
    cycle["scheduled_end"] = cycle["scheduled_start"] + timedelta(seconds=seconds)
    cycle["estimated_tolling_fee_cents"] = calc.tolling_fee_cents(
        seconds, cycle["utilization_pct"])


def actual_fee_cents(cycle, log):
    """ACTUAL variant: measured come-up and hold out of the CCP record."""
    vessel = vessel_of(cycle)
    total = sum(r["baskets_used"] for r in live_loads(cycle["id"]))
    cycle["baskets_used_total"] = total
    cycle["utilization_pct"] = calc.utilization_pct(total, vessel["basket_count"])
    seconds = calc.cycle_seconds(log["come_up_seconds"], log["actual_hold_seconds"],
                                 vessel["decompression_seconds"])
    cycle["actual_cycle_seconds"] = seconds
    return calc.tolling_fee_cents(seconds, cycle["utilization_pct"])


def allocate_fee_to_loads(cycle, total_cents, participants):
    def peak_factor(load):
        contract = db.contracts.get(load["contract_id"])
        if contract is None:
            return None
        if (contract["peak_window_start"] <= cycle["scheduled_start"]
                <= contract["peak_window_end"]):
            return contract["peak_multiplier"]
        return None

    return calc.allocate_fee(total_cents, participants, peak_factor)


def chamber_requirements(loads):
    """Strictest recipe across the loaded pallets (PRD 3.6)."""
    pressures = []
    holds = []
    temps = []
    for load in loads:
        qualification = qualification_of(lot_of(load)) if lot_of(load) else None
        if qualification is None:
            continue
        pressures.append(calc.D(qualification["pressure_mpa"]))
        holds.append(int(qualification["hold_time_seconds"]))
        temps.append(calc.D(qualification["max_water_temp_c"]))
    return (max(pressures) if pressures else None,
            max(holds) if holds else None,
            min(temps) if temps else None)
