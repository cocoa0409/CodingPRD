"""Cascading side effects (PRD §3.4, §3.5).

These functions implement the multi-hop ripples that the skill warns are where
the tricky bugs hide. Every resource touched along the way has its updated_at
refreshed and its version bumped independently — but only when its own state
actually changes (recompute helpers handle the "changed?" guard).
"""
from db import db, touch
import domain


def cancel_workorder(wo):
    """Drive a work order to CANCELLED and run the full cancel side-effects:
      - credit the system's committed_cost_cents back (recompute)
      - drive any SCHEDULED RouteStop referencing it to REMOVED, recomputing
        that stop's route stops_used / minutes_committed.

    Caller is responsible for the terminal-state precondition. Used both by the
    POST /work-orders/{id}/cancel endpoint and by the decommission cascade.
    """
    wo["completion_status"] = "CANCELLED"
    touch(wo)

    # Remove SCHEDULED route stops that reference this work order.
    affected_routes = set()
    for rs in db.route_stops.values():
        if rs["work_order_id"] == wo["id"] and rs["stop_state"] == "SCHEDULED":
            rs["stop_state"] = "REMOVED"
            touch(rs)
            affected_routes.add(rs["route_id"])
    for route_id in affected_routes:
        route = db.routes.get(route_id)
        if route:
            domain.recompute_route_derived(route)

    # Credit committed_cost back by recomputing the system's derived fields
    # (committed_cost_cents excludes terminal work orders).
    system = db.irrigation_systems.get(wo["system_id"])
    if system:
        domain.recompute_system_derived(system)


def decommission_system(system):
    """Depth-3 cascade (PRD §3.5):
      HOP 1: every non-ARCHIVED zone -> ARCHIVED
      HOP 2: each ACTIVE program referencing a just-archived zone -> STALE
      HOP 3: every non-terminal work order on the system -> CANCELLED (full
             cancel side-effects each)
      Finally: property compliance recomputed; system derived recomputed.
    Caller checks the OPERATIONAL precondition.
    """
    system["lifecycle_state"] = "DECOMMISSIONED"
    touch(system)

    # HOP 1
    archived_zone_ids = set()
    for z in domain.zones_of_system(system["id"]):
        if z["zone_state"] != "ARCHIVED":
            z["zone_state"] = "ARCHIVED"
            touch(z)
            archived_zone_ids.add(z["id"])

    # HOP 2: ACTIVE programs whose slots reference a just-archived zone -> STALE
    for prog in db.controller_programs.values():
        if prog["system_id"] != system["id"]:
            continue
        if prog["program_state"] != "ACTIVE":
            continue
        slot_zone_ids = {s["zone_id"] for s in prog["slots"]}
        if slot_zone_ids & archived_zone_ids:
            prog["program_state"] = "STALE"
            touch(prog)

    # HOP 3: cancel non-terminal work orders (full cancel side-effects each)
    for wo in list(domain.workorders_of_system(system["id"])):
        if wo["completion_status"] not in domain.WO_TERMINAL:
            cancel_workorder(wo)

    # System derived (zone_count, committed_cost, risks) reflect the cascade.
    domain.recompute_system_derived(system)

    # Property compliance reflects the system's removal from the compliant set.
    prop = db.properties.get(system["property_id"])
    if prop:
        domain.recompute_property_compliance(prop)


def record_backflow_cascade(system):
    """Bubble-up after a backflow test sets system.backflow_status: recompute
    the owning property's compliance_status."""
    domain.recompute_system_derived(system)
    prop = db.properties.get(system["property_id"])
    if prop:
        domain.recompute_property_compliance(prop)
