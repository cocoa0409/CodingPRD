"""Plant derived state: the shared silo balance (PRD 2.8) and the production
posture gate (PRD 2.9)."""

from decimal import Decimal

import calc
from db import bump, db, ordered
from util import D, rhu


# ------------------------------------------------------------------ lookups
def runs_of_plant(plant_id):
    return [r for r in ordered(db.production_runs) if r["plant_id"] == plant_id]


def lines_of_plant(plant_id):
    return [l for l in ordered(db.board_lines) if l["plant_id"] == plant_id]


def loads_of_run(run_id):
    return [lo for lo in ordered(db.load_orders) if lo["run_id"] == run_id]


def plant_of_run(run):
    return db.plants.get(run["plant_id"])


def plant_of_line(line):
    return db.plants.get(line["plant_id"])


def emergency_active(plant_id):
    line_ids = {l["id"] for l in lines_of_plant(plant_id)}
    for outage in db.maintenance_outages.values():
        if (
            outage["line_id"] in line_ids
            and outage["status"] == "IN_PROGRESS"
            and outage["outage_type"] == "EMERGENCY"
        ):
            return True
    return False


# ------------------------------------------------------- derived recompute
def recompute_plant_derived(plant):
    """Rewrites held_run_count, stucco_committed_tons, stucco_available_tons and
    production_posture in place. Does NOT bump the version."""
    runs = runs_of_plant(plant["id"])
    plant["held_run_count"] = sum(1 for r in runs if r["quality_state"] == "HELD")

    committed = Decimal(0)
    for r in runs:
        if r["status"] in ("SCHEDULED", "RUNNING"):
            committed += D(r["stucco_reserved_tons"])
    plant["stucco_committed_tons"] = rhu(committed, 3)
    plant["stucco_on_hand_tons"] = rhu(D(plant["stucco_on_hand_tons"]), 3)
    plant["stucco_available_tons"] = rhu(
        D(plant["stucco_on_hand_tons"]) - D(plant["stucco_committed_tons"]), 3
    )
    plant["production_posture"] = calc.production_posture(
        plant["held_run_count"],
        plant["stucco_available_tons"],
        emergency_active(plant["id"]),
    )
    return plant


def settle_plant(plant):
    """Re-derive plant state and record the mutation (PRD 2.9 / 2.4)."""
    recompute_plant_derived(plant)
    bump(plant)
    return plant


def credit_silo(plant, tons):
    plant["stucco_on_hand_tons"] = rhu(D(plant["stucco_on_hand_tons"]) + D(tons), 3)


def debit_silo(plant, tons):
    plant["stucco_on_hand_tons"] = rhu(D(plant["stucco_on_hand_tons"]) - D(tons), 3)


# ------------------------------------------------------------- run volumes
def recompute_available_msf(run):
    committed = Decimal(0)
    for lo in loads_of_run(run["id"]):
        if lo["status"] in ("STAGED", "HELD", "LOADED", "SHIPPED"):
            committed += D(lo["total_msf"])
    run["available_msf"] = rhu(D(run["net_good_msf"]) - committed, 3)
    return run["available_msf"]


# ------------------------------------------------------------- lot balances
def recompute_lot_balance(lot):
    consumed = Decimal(0)
    for feed in db.batch_feeds.values():
        if feed["lot_id"] != lot["id"]:
            continue
        batch = db.calciner_batches.get(feed["batch_id"])
        if batch is None or batch["status"] == "ABORTED":
            continue
        consumed += D(feed["tons_fed"])
    lot["consumed_tons"] = rhu(consumed, 3)
    lot["remaining_tons"] = rhu(D(lot["received_tons"]) - D(lot["consumed_tons"]), 3)
    return lot["remaining_tons"]
