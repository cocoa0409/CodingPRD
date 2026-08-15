"""Domain services: computed totals and cascade side effects (§3)."""

from db import db
from helpers import touch


# ---------------------------------------------------------------------------
# Computed totals (§3.1)
# ---------------------------------------------------------------------------

def recompute_season_committed_acres(season):
    """Sum of committed_acres across contracts in COMMITTED / IN_PROGRESS /
    HARVESTED status."""
    total = 0
    for c in db.contracts.values():
        if c["season_id"] == season["id"] and c["status"] in (
            "COMMITTED",
            "IN_PROGRESS",
            "HARVESTED",
        ):
            total += c.get("committed_acres", 0)
    season["committed_acres_total"] = total


def recompute_season_harvested_acres(season):
    """Sum of actual_acres across route stops whose status is COMPLETED."""
    total = 0
    for s in db.route_stops.values():
        if s["season_id"] == season["id"] and s["status"] == "COMPLETED":
            total += s.get("actual_acres", 0)
    season["harvested_acres_total"] = total


def recompute_contract_harvested_acres(contract):
    """Sum of actual_acres over this contract's COMPLETED stops."""
    total = 0
    for s in db.route_stops.values():
        if s["contract_id"] == contract["id"] and s["status"] == "COMPLETED":
            total += s.get("actual_acres", 0)
    contract["harvested_acres"] = total


# ---------------------------------------------------------------------------
# Machine allocation helpers (§3.4, §3.5)
# ---------------------------------------------------------------------------

def machine_has_active_assignment(machine_id, exclude_assignment_id=None):
    """Any non-CANCELLED, non-RELEASED assignment exists for this machine."""
    for a in db.machine_assignments.values():
        if a["machine_id"] != machine_id:
            continue
        if exclude_assignment_id is not None and a["id"] == exclude_assignment_id:
            continue
        if a["status"] in ("RESERVED", "DEPLOYED"):
            return True
    return False


def machine_has_deployed_assignment(machine_id, exclude_assignment_id=None):
    for a in db.machine_assignments.values():
        if a["machine_id"] != machine_id:
            continue
        if exclude_assignment_id is not None and a["id"] == exclude_assignment_id:
            continue
        if a["status"] == "DEPLOYED":
            return True
    return False


def release_machine_if_unallocated(machine_id, exclude_assignment_id=None):
    """Return a machine to AVAILABLE when it no longer has any active
    assignment. Applies when the machine is ASSIGNED (last reservation
    cancelled) or IN_FIELD (last deployed assignment released)."""
    machine = db.machines.get(machine_id)
    if machine is None:
        return
    if machine["status"] == "ASSIGNED":
        if not machine_has_active_assignment(machine_id, exclude_assignment_id):
            machine["status"] = "AVAILABLE"
            touch(machine)
    elif machine["status"] == "IN_FIELD":
        if not machine_has_deployed_assignment(machine_id, exclude_assignment_id):
            machine["status"] = "AVAILABLE"
            touch(machine)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def skip_stop_cascade(stop):
    """SCHEDULED → SKIPPED side effects: RESERVED assignments → CANCELLED
    (machines released if unallocated); BOOKED lodging → CANCELLED."""
    stop["status"] = "SKIPPED"
    touch(stop)
    for a in db.machine_assignments.values():
        if a["route_stop_id"] == stop["id"] and a["status"] == "RESERVED":
            a["status"] = "CANCELLED"
            touch(a)
            release_machine_if_unallocated(a["machine_id"], exclude_assignment_id=a["id"])
    for r in db.lodging_reservations.values():
        if r["route_stop_id"] == stop["id"] and r["status"] == "BOOKED":
            r["status"] = "CANCELLED"
            touch(r)


def maybe_contract_harvested(contract):
    """If every RouteStop of the contract is COMPLETED or SKIPPED, the
    contract auto-transitions IN_PROGRESS → HARVESTED."""
    stops = [s for s in db.route_stops.values() if s["contract_id"] == contract["id"]]
    if not stops:
        return
    if all(s["status"] in ("COMPLETED", "SKIPPED") for s in stops):
        if contract["status"] == "IN_PROGRESS":
            contract["status"] = "HARVESTED"
            touch(contract)
