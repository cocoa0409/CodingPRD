"""Immediate multi-hop cascades (PRD 2.12). Every touched row is a mutation of
its own and bumps its own version."""

from db import bump
from services.plant import (
    loads_of_run,
    recompute_available_msf,
    settle_plant,
)
from util import ZERO3


# ------------------------------------------------------------- load orders
def hold_staged_loads(run):
    """A run's quality_state went HELD: its STAGED loads follow (PRD 3.8)."""
    touched = []
    for load in loads_of_run(run["id"]):
        if load["status"] == "STAGED":
            load["status"] = "HELD"
            load["hold_source"] = "RUN_QUALITY_HELD"
            bump(load)
            touched.append(load)
    return touched


def release_held_loads(run):
    """A run returned to RELEASED / DOWNGRADED: its HELD loads go back to STAGED."""
    touched = []
    for load in loads_of_run(run["id"]):
        if load["status"] == "HELD":
            load["status"] = "STAGED"
            load["hold_source"] = None
            bump(load)
            touched.append(load)
    return touched


def cancel_loads(run, reason, statuses=("STAGED", "HELD", "LOADED")):
    touched = []
    for load in loads_of_run(run["id"]):
        if load["status"] in statuses:
            load["status"] = "CANCELLED"
            load["cancel_reason"] = reason
            bump(load)
            touched.append(load)
    if touched:
        recompute_available_msf(run)
    return touched


# --------------------------------------------------------------------- runs
def hold_run(run, plant, held_reason):
    """Move a run's quality dimension to HELD and cascade downstream."""
    run["quality_state"] = "HELD"
    run["held_reason"] = held_reason
    run["saleable_grade"] = "UNGRADED"
    bump(run)
    hold_staged_loads(run)
    settle_plant(plant)
    return run


def cancel_run(run, plant, reason):
    """Cancel a DRAFT or SCHEDULED run, releasing any reservation and its loads."""
    was_scheduled = run["status"] == "SCHEDULED"
    run["status"] = "CANCELLED"
    run["cancel_reason"] = reason
    if was_scheduled:
        run["stucco_reserved_tons"] = ZERO3
    bump(run)
    cancel_loads(run, None)
    if was_scheduled:
        settle_plant(plant)
    return run
