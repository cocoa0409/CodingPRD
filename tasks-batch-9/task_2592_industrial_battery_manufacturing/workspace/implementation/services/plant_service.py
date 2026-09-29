"""Plant posture, emission ledger, lead mass balance and the environmental cascade."""
from decimal import Decimal

from helpers import lots_of_plant, runs_of_lot, units_of_plant
from store import db
from util import q
from services.constants import (
    ABORT_REASON_ENV_CASCADE,
    CORE_DEPOSIT_CENTS,
    HOLDABLE_LOT_STATES,
    HOLD_REASON_PERMIT_SUSPENDED,
    HOLD_REASON_PLANT_FROZEN,
    POSTURE_FROZEN,
    POSTURE_FROZEN_RATIO,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    POSTURE_RESTRICTED_RATIO,
)

OUTSTANDING_CORE_STATES = ("DEPOSIT_HELD", "RETURN_OPEN", "IN_TRANSIT")
# The deposit is opened at shipment and discharged only by RECYCLE (refund) or
# REJECT (forfeit) -- PRD 3.9 is explicit that receipt does NOT settle it.
DEPOSIT_HELD_CORE_STATES = ("DEPOSIT_HELD", "RETURN_OPEN", "IN_TRANSIT", "RECEIVED")
RETURNED_CORE_STATES = ("RECEIVED", "RECYCLED", "REJECTED")
RECEIVED_CORE_STATES = ("RECEIVED", "RECYCLED")


def workers_of_plant(plant_id):
    return [w for w in db.workers.values() if w.get("plant_id") == plant_id]


def runs_of_plant(plant_id):
    lot_ids = {lot["id"] for lot in lots_of_plant(plant_id)}
    return [r for r in db.formation_runs.values() if r.get("lot_id") in lot_ids]


def _same_permit_month(moment, now):
    return moment is not None and (moment.year, moment.month) == (now.year, now.month)


def recompute_emissions(plant):
    now = db.now()
    reserved = Decimal("0")
    consumed = Decimal("0")
    charges = 0
    for run in runs_of_plant(plant["id"]):
        state = run.get("run_state")
        if state in ("SCHEDULED", "CHARGING"):
            reserved += run.get("reserved_emission_g") or Decimal("0")
        if state == "COMPLETED":
            charges += run.get("final_charge_cents") or 0
            if _same_permit_month(run.get("actual_end_at"), now):
                consumed += run.get("consumed_emission_g") or Decimal("0")
    plant["emission_reserved_g"] = q(reserved, 2)
    plant["emission_consumed_g"] = q(consumed, 2)
    plant["formation_energy_charge_cents"] = charges
    permit = plant["monthly_lead_emission_permit_g"]
    ratio = (reserved + consumed) / permit if permit and permit != 0 else Decimal("0")
    plant["emission_utilization_ratio"] = q(ratio, 4)
    return plant["emission_utilization_ratio"]


def recompute_lead_balance(plant):
    initial = plant["lead_initial_inventory_kg"]
    shipped = Decimal("0")
    in_field = Decimal("0")
    recycled = Decimal("0")
    variance = Decimal("0")
    outstanding = 0
    for unit in units_of_plant(plant["id"]):
        declared = unit.get("declared_lead_kg") or Decimal("0")
        shipped += declared
        status = unit.get("core_status")
        if status in OUTSTANDING_CORE_STATES:
            in_field += declared
        elif status in RETURNED_CORE_STATES:
            recycled += declared
        if status in DEPOSIT_HELD_CORE_STATES:
            outstanding += 1
        if status in RECEIVED_CORE_STATES and unit.get("received_lead_kg") is not None:
            variance += unit["received_lead_kg"] - declared
    inventory = q(initial - shipped, 3)
    plant["lead_inventory_kg"] = inventory
    plant["lead_in_field_kg"] = q(in_field, 3)
    plant["lead_recycled_kg"] = q(recycled, 3)
    plant["lead_mass_variance_kg"] = q(
        initial - (inventory + plant["lead_in_field_kg"] + plant["lead_recycled_kg"]), 3
    )
    plant["core_lead_variance_kg"] = q(variance, 3)
    plant["core_deposit_liability_cents"] = CORE_DEPOSIT_CENTS * outstanding
    return plant


def open_removal_count(plant):
    count = sum(
        1
        for worker in workers_of_plant(plant["id"])
        if worker.get("removal_status") == "MEDICAL_REMOVAL"
    )
    plant["open_medical_removal_count"] = count
    return count


def derive_posture(plant):
    """PRD 3.1 / calculation 6: permit and removals dominate, then utilisation."""
    ratio = plant["emission_utilization_ratio"]
    removals = plant["open_medical_removal_count"]
    if plant.get("permit_status") == "SUSPENDED":
        return POSTURE_FROZEN
    if removals >= 2:
        return POSTURE_FROZEN
    if ratio >= POSTURE_FROZEN_RATIO:
        return POSTURE_FROZEN
    if removals == 1:
        return POSTURE_RESTRICTED
    if ratio >= POSTURE_RESTRICTED_RATIO:
        return POSTURE_RESTRICTED
    return POSTURE_OPEN


def abort_run(run, reason):
    run["run_state"] = "ABORTED"
    run["abort_reason"] = reason
    db.touch(run)


def _hold_cascade(plant, reason):
    """Cascade A hops 4 and 5."""
    for lot in lots_of_plant(plant["id"]):
        if lot.get("process_state") not in HOLDABLE_LOT_STATES:
            continue
        if lot.get("env_hold_status") != "CLEAR":
            continue
        lot["env_hold_status"] = "HELD"
        lot["hold_reason"] = reason
        db.touch(lot)
        for run in runs_of_lot(lot["id"]):
            if run.get("run_state") == "CHARGING":
                abort_run(run, ABORT_REASON_ENV_CASCADE)


def _lift_holds(plant, reasons):
    for lot in lots_of_plant(plant["id"]):
        if lot.get("env_hold_status") != "HELD":
            continue
        if lot.get("hold_reason") not in reasons:
            continue
        lot["env_hold_status"] = "CLEAR"
        lot["hold_reason"] = None
        db.touch(lot)


def refresh_plant(plant, permit_suspended=False, permit_reinstated=False):
    """Recompute every derived plant figure, then run the posture cascade.

    The posture is derived exactly once per request: releasing reservations
    inside the hold cascade updates the ledger sums but never re-derives the
    posture, so a freeze that the cascade itself relieves still stands.
    """
    before = {
        "emission_reserved_g": plant.get("emission_reserved_g"),
        "emission_consumed_g": plant.get("emission_consumed_g"),
        "emission_utilization_ratio": plant.get("emission_utilization_ratio"),
        "formation_energy_charge_cents": plant.get("formation_energy_charge_cents"),
        "open_medical_removal_count": plant.get("open_medical_removal_count"),
        "compliance_posture": plant.get("compliance_posture"),
        "lead_inventory_kg": plant.get("lead_inventory_kg"),
        "lead_in_field_kg": plant.get("lead_in_field_kg"),
        "lead_recycled_kg": plant.get("lead_recycled_kg"),
        "core_lead_variance_kg": plant.get("core_lead_variance_kg"),
        "core_deposit_liability_cents": plant.get("core_deposit_liability_cents"),
    }
    recompute_emissions(plant)
    recompute_lead_balance(plant)
    open_removal_count(plant)
    previous_posture = plant.get("compliance_posture")
    posture = derive_posture(plant)
    plant["compliance_posture"] = posture
    if permit_suspended:
        _hold_cascade(plant, HOLD_REASON_PERMIT_SUSPENDED)
        recompute_emissions(plant)
    elif posture == POSTURE_FROZEN and previous_posture != POSTURE_FROZEN:
        _hold_cascade(plant, HOLD_REASON_PLANT_FROZEN)
        recompute_emissions(plant)
    elif posture != POSTURE_FROZEN and previous_posture == POSTURE_FROZEN:
        reasons = {HOLD_REASON_PLANT_FROZEN}
        if permit_reinstated:
            reasons.add(HOLD_REASON_PERMIT_SUSPENDED)
        _lift_holds(plant, reasons)
    elif permit_reinstated and posture != POSTURE_FROZEN:
        _lift_holds(plant, {HOLD_REASON_PLANT_FROZEN, HOLD_REASON_PERMIT_SUSPENDED})
    if any(plant.get(key) != value for key, value in before.items()):
        db.touch(plant)
    return plant


def emission_ledger(plant):
    # Reads never recompute: repositioning the logical clock is not retroactive,
    # so the stored derived figures are the ones every write left behind.
    lines = []
    runs = sorted(
        runs_of_plant(plant["id"]),
        key=lambda r: (r.get("scheduled_start_at"), r.get("created_at"), r.get("_seq")),
    )
    for run in runs:
        lines.append(
            {
                "run_id": run["id"],
                "lot_id": run.get("lot_id"),
                "bay_id": run.get("bay_id"),
                "run_state": run.get("run_state"),
                "reserved_emission_g": run.get("reserved_emission_g"),
                "consumed_emission_g": run.get("consumed_emission_g"),
                "estimated_energy_kwh": run.get("estimated_energy_kwh"),
                "metered_energy_kwh": run.get("metered_energy_kwh"),
                "provisional_charge_cents": run.get("provisional_charge_cents"),
                "final_charge_cents": run.get("final_charge_cents"),
                "scheduled_start_at": run.get("scheduled_start_at"),
                "actual_end_at": run.get("actual_end_at"),
            }
        )
    return {
        "plant_id": plant["id"],
        "monthly_lead_emission_permit_g": plant["monthly_lead_emission_permit_g"],
        "emission_reserved_g": plant["emission_reserved_g"],
        "emission_consumed_g": plant["emission_consumed_g"],
        "emission_utilization_ratio": plant["emission_utilization_ratio"],
        "compliance_posture": plant["compliance_posture"],
        "open_medical_removal_count": plant["open_medical_removal_count"],
        "formation_energy_charge_cents": plant["formation_energy_charge_cents"],
        "lines": lines,
    }


def lead_mass_balance(plant):
    return {
        "plant_id": plant["id"],
        "lead_initial_inventory_kg": plant["lead_initial_inventory_kg"],
        "lead_inventory_kg": plant["lead_inventory_kg"],
        "lead_in_field_kg": plant["lead_in_field_kg"],
        "lead_recycled_kg": plant["lead_recycled_kg"],
        "lead_mass_variance_kg": plant["lead_mass_variance_kg"],
        "core_lead_variance_kg": plant["core_lead_variance_kg"],
        "core_deposit_liability_cents": plant["core_deposit_liability_cents"],
    }
