"""Multi-record cascades (PRD 2.10, 3.6, 3.9).

Every record a cascade actually changes has its updated_at refreshed and its
version bumped exactly once; records the cascade did not change are left alone.
"""
from decimal import Decimal

import calc
import clock
import db
import queries
from util import dec, q2

ZERO = Decimal("0.00")


# ------------------------------------------------------------- vibration hold
def apply_hold(phase, hold_reason):
    """PRD 3.6: hold the phase, block the downstream chain, suspend the project,
    preempt the project's future amenity allocations."""
    phase["status"] = "VIBRATION_HOLD"
    phase["hold_reason"] = hold_reason
    db.touch(phase)

    for successor in queries.transitive_successors(phase["id"]):
        if successor["status"] in ("DRAFT", "SCHEDULED"):
            successor["prior_status"] = successor["status"]
            successor["status"] = "BLOCKED"
            db.touch(successor)

    project = db.projects.get(phase["project_id"])
    if project is not None and project["construction_status"] == "C_IN_PROGRESS":
        project["construction_status"] = "C_SUSPENDED"
        db.touch(project)

    now = clock.now()
    for allocation in queries.allocations_of_project(phase["project_id"]):
        if allocation["status"] in ("REQUESTED", "CONFIRMED") and allocation["window_start"] >= now:
            allocation["status"] = "PREEMPTED"
            db.touch(allocation)


def release_hold(phase):
    """PRD 3.6: restore the blocked chain verbatim and resume the project."""
    for successor in queries.transitive_successors(phase["id"]):
        if successor["status"] == "BLOCKED" and successor["prior_status"] is not None:
            successor["status"] = successor["prior_status"]
            successor["prior_status"] = None
            db.touch(successor)

    project = db.projects.get(phase["project_id"])
    if project is None:
        return
    for sibling in queries.phases_of_project(project["id"]):
        if sibling["status"] in ("VIBRATION_HOLD", "BLOCKED"):
            return
    if project["construction_status"] == "C_SUSPENDED":
        project["construction_status"] = "C_IN_PROGRESS"
        db.touch(project)


# ---------------------------------------------------------- project acceptance
def accept_project(project):
    """PRD 3.9 four-hop cascade fired by the final passing script."""
    project["construction_status"] = "C_ACCEPTED"
    project["accepted_at"] = clock.now()
    db.touch(project)

    buildings_touched = set()
    for reservation in queries.reservations_of_project(project["id"]):
        if reservation["status"] != "RESERVED":
            continue
        reservation["status"] = "COMMITTED"
        db.touch(reservation)
        buildings_touched.add(reservation["building_id"])
    for building_id in buildings_touched:
        building = db.buildings.get(building_id)
        if building is not None:
            db.touch(building)

    for permit in queries.permits_of_project(project["id"]):
        if permit["status"] == "APPROVED":
            permit["status"] = "ACTIVE"
            db.touch(permit)

    lease = queries.lease_of_project(project)
    if lease is not None and lease["status"] == "EXECUTED":
        lease["status"] = "ACTIVE"
        db.touch(lease)


# -------------------------------------------------------- commissioning FAIL
def reverse_last_draw(lease):
    """PRD 3.9: reverse the most recent draw exactly, then zero the marker."""
    amount = dec(lease["last_disbursement_usd"])
    if amount <= 0:
        return False
    allocations = lease.get("_last_draw_allocations") or {}
    for phase_id, allocated in allocations.items():
        phase = db.phases.get(phase_id)
        if phase is None:
            continue
        phase["ti_disbursed_usd"] = q2(dec(phase["ti_disbursed_usd"]) - dec(allocated))
        db.touch(phase)
    lease["ti_disbursed_usd"] = q2(dec(lease["ti_disbursed_usd"]) - amount)
    lease["ti_committed_usd"] = q2(dec(lease["ti_committed_usd"]) + amount)
    lease["last_disbursement_usd"] = ZERO
    lease["_last_draw_allocations"] = {}
    db.touch(lease)
    return True


# -------------------------------------------------------- restoration settlement
def settle_restoration(lease):
    """PRD 3.9 settlement waterfall in its normative order."""
    liability = calc.restoration_liability(lease)
    lease["restoration_liability_usd"] = liability

    held = dec(lease["restoration_escrow_held_usd"])
    escrow_applied = min(held, liability)
    lease["restoration_escrow_refunded_usd"] = q2(held - escrow_applied)
    lease["restoration_escrow_held_usd"] = ZERO

    remaining = q2(liability - escrow_applied)
    uncommitted = dec(lease["ti_uncommitted_usd"])
    clawback = min(remaining, uncommitted)
    uncommitted = q2(uncommitted - clawback)
    lease["restoration_cash_due_usd"] = q2(remaining - clawback)

    committed = dec(lease["ti_committed_usd"])
    lease["ti_forfeited_usd"] = q2(dec(lease["ti_forfeited_usd"]) + clawback + uncommitted + committed)
    lease["ti_uncommitted_usd"] = ZERO
    lease["ti_committed_usd"] = ZERO

    for permit in queries.permits_of_lease(lease["id"]):
        if permit["status"] in ("APPROVED", "ACTIVE"):
            permit["status"] = "SURRENDERED"
            db.touch(permit)

    buildings_touched = set()
    for reservation in queries.reservations_of_lease(lease["id"]):
        if reservation["status"] not in ("RESERVED", "COMMITTED"):
            continue
        reservation["status"] = "RELEASED"
        db.touch(reservation)
        buildings_touched.add(reservation["building_id"])
    for building_id in buildings_touched:
        building = db.buildings.get(building_id)
        if building is not None:
            db.touch(building)

    lease["status"] = "SURRENDERED"
    db.touch(lease)
    return lease
