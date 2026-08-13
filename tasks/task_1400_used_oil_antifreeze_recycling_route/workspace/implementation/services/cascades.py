"""Cross-entity cascades and derived-state reconciliation (PRD §2.9).

Every mutation of a resource refreshes its updated_at and increments its
version, including mutations driven by cascades and derived-field updates.
"""

import db


# Stop states
NON_TERMINAL_STOP_STATES = {"SCHEDULED", "EN_ROUTE", "SCREENING", "READY_TO_PUMP"}
TERMINAL_STOP_STATES = {
    "COMPLETED",
    "SKIPPED_BELOW_MINIMUM",
    "CANCELLED_HALOGEN",
    "CANCELLED_ROUTE",
    "CANCELLED_CUSTOMER",
}


def stops_for_route(route_id):
    return [s for s in db.all_entities("route_stops") if s["route_id"] == route_id]


def tickets_for_stop(route_stop_id):
    return [t for t in db.all_entities("pickup_tickets") if t["route_stop_id"] == route_stop_id]


def manifest_for_route(route_id):
    for m in db.all_entities("manifests"):
        if m["route_id"] == route_id:
            return m
    return None


def customer_of_site(site):
    return db.get("customers", site["customer_id"]) if site else None


def customer_of_ticket(ticket):
    stop = db.get("route_stops", ticket["route_stop_id"])
    if not stop:
        return None
    site = db.get("tank_sites", stop["tank_site_id"])
    return customer_of_site(site)


# ---------------------------------------------------------------------------
# Tank / site hazard cascades
# ---------------------------------------------------------------------------


def quarantine_tank(tank, cancel_stops):
    """CLEAR -> QUARANTINED. When the trigger is a halogen screen
    (cancel_stops=True), every SCHEDULED/EN_ROUTE stop on the tank is
    cancelled to CANCELLED_HALOGEN. The sticky _was_quarantined marker feeds
    the manifest halogen_flag."""
    if tank["quarantine_status"] != "QUARANTINED":
        tank["quarantine_status"] = "QUARANTINED"
        db.touch(tank)
    tank["_was_quarantined"] = True
    if cancel_stops:
        for stop in db.all_entities("route_stops"):
            if stop["tank_id"] == tank["id"] and stop["status"] in ("SCHEDULED", "EN_ROUTE"):
                stop["status"] = "CANCELLED_HALOGEN"
                db.touch(stop)


def contaminate_site(site):
    """ACTIVE -> CONTAMINATED; every tank at the site is quarantined."""
    if site["status"] != "CONTAMINATED":
        site["status"] = "CONTAMINATED"
        site["_inactivated_by_cascade"] = False
        db.touch(site)
    for tank in db.all_entities("tanks"):
        if tank["tank_site_id"] == site["id"]:
            if tank["quarantine_status"] != "QUARANTINED":
                tank["quarantine_status"] = "QUARANTINED"
                db.touch(tank)
            tank["_was_quarantined"] = True


# ---------------------------------------------------------------------------
# Customer lifecycle cascades
# ---------------------------------------------------------------------------


def sites_of_customer(customer_id):
    return [s for s in db.all_entities("tank_sites") if s["customer_id"] == customer_id]


def tanks_of_site(site_id):
    return [t for t in db.all_entities("tanks") if t["tank_site_id"] == site_id]


def cascade_customer_suspend(customer):
    """Sites -> INACTIVE (marked as cascade-driven); future-dated SCHEDULED
    stops referencing any tank at those sites -> CANCELLED_CUSTOMER."""
    today = db.today_iso()
    site_ids = set()
    for site in sites_of_customer(customer["id"]):
        site_ids.add(site["id"])
        if site["status"] != "INACTIVE":
            site["status"] = "INACTIVE"
            site["_inactivated_by_cascade"] = True
            db.touch(site)
    for stop in db.all_entities("route_stops"):
        if stop["tank_site_id"] not in site_ids or stop["status"] != "SCHEDULED":
            continue
        route = db.get("routes", stop["route_id"])
        if route and route["scheduled_date"] >= today:
            stop["status"] = "CANCELLED_CUSTOMER"
            db.touch(stop)


def cascade_customer_reinstate(customer):
    """Sites inactivated by the suspension cascade (not by an explicit
    planner deactivate) return to ACTIVE."""
    for site in sites_of_customer(customer["id"]):
        if site["status"] == "INACTIVE" and site.get("_inactivated_by_cascade"):
            site["status"] = "ACTIVE"
            site["_inactivated_by_cascade"] = False
            db.touch(site)


def cascade_customer_terminate(customer):
    """Sites -> INACTIVE; every tank (not already DECOMMISSIONED) ->
    DECOMMISSION_PENDING; every non-terminal stop on those tanks ->
    CANCELLED_CUSTOMER."""
    site_ids = set()
    for site in sites_of_customer(customer["id"]):
        site_ids.add(site["id"])
        if site["status"] != "INACTIVE":
            site["status"] = "INACTIVE"
            site["_inactivated_by_cascade"] = False
            db.touch(site)
        for tank in tanks_of_site(site["id"]):
            if tank["ownership_status"] != "DECOMMISSIONED":
                tank["ownership_status"] = "DECOMMISSION_PENDING"
                db.touch(tank)
    for stop in db.all_entities("route_stops"):
        if stop["tank_site_id"] in site_ids and stop["status"] in NON_TERMINAL_STOP_STATES:
            stop["status"] = "CANCELLED_CUSTOMER"
            db.touch(stop)


# ---------------------------------------------------------------------------
# Route / manifest reconciliation
# ---------------------------------------------------------------------------


def recompute_manifest_totals(manifest):
    """total_gallons_manifested = sum of metered volumes from the route's
    COMPLETED stops; halogen_flag = any completed pickup came from a
    previously quarantined tank."""
    total = 0
    halogen = False
    for stop in stops_for_route(manifest["route_id"]):
        if stop["status"] != "COMPLETED":
            continue
        for ticket in tickets_for_stop(stop["id"]):
            total += ticket["metered_volume_gallons"]
            tank = db.get("tanks", stop["tank_id"])
            if tank and tank.get("_was_quarantined"):
                halogen = True
    changed = (
        manifest["total_gallons_manifested"] != total
        or manifest["halogen_flag"] != halogen
    )
    manifest["total_gallons_manifested"] = total
    manifest["halogen_flag"] = halogen
    if changed:
        db.touch(manifest)


def facility_scheduled_gallons_today(facility_id):
    """Derived: sum of total_gallons_manifested across manifests in
    SUBMITTED / IN_TRANSIT / AMENDMENT_PENDING whose route's scheduled_date
    equals the server's current logical date."""
    today = db.today_iso()
    total = 0
    for m in db.all_entities("manifests"):
        if m["disposal_facility_id"] != facility_id:
            continue
        if m["status"] not in ("SUBMITTED", "IN_TRANSIT", "AMENDMENT_PENDING"):
            continue
        route = db.get("routes", m["route_id"])
        if route and route["scheduled_date"] == today:
            total += m["total_gallons_manifested"]
    return total
