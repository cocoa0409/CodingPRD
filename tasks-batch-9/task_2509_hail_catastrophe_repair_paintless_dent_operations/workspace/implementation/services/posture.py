"""Facility posture: the master gate (PRD §2.6, calculations.facility_posture).

Recomputation is lazy: it runs at the start of every request that reads or mutates
a facility, or that reads or mutates any of that facility's permits, housing units,
crew deployments or vehicles. It can expire permits and drive the
COMMISSIONED <-> SUSPENDED cycle inside whichever request triggered it.
"""

from clock import clock, parse_date
from db import db, touch
from numeric import D, round_half_up
from services import aggregates
from services.constants import REQUIRED_PERMIT_TYPES


def _expire_lapsed_permits(facility, clock_date):
    for permit in aggregates.permits_of_facility(facility["id"]):
        if permit["status"] != "APPROVED":
            continue
        valid_to = parse_date(permit["valid_to"]) if permit.get("valid_to") else None
        if valid_to is not None and valid_to < clock_date:
            permit["status"] = "EXPIRED"


def permit_coverage_ok(facility, clock_date):
    for required_type in REQUIRED_PERMIT_TYPES:
        covered = False
        for permit in aggregates.permits_of_facility(facility["id"]):
            if permit["permit_type"] != required_type or permit["status"] != "APPROVED":
                continue
            valid_from = parse_date(permit["valid_from"]) if permit.get("valid_from") else None
            valid_to = parse_date(permit["valid_to"]) if permit.get("valid_to") else None
            if valid_from is None or valid_to is None:
                continue
            if valid_from <= clock_date <= valid_to:
                covered = True
                break
        if not covered:
            return False
    return True


def on_site_licensed_technician_count(facility, clock_date):
    seen = set()
    for deployment in aggregates.deployments_of_facility(facility["id"]):
        if deployment["status"] != "ON_SITE":
            continue
        technician = db.technicians.get(deployment["technician_id"])
        if technician is None:
            continue
        if technician["license_state_code"] != facility["state_code"]:
            continue
        expires = parse_date(technician["license_expires_at"])
        if expires is None or expires < clock_date:
            continue
        seen.add(technician["id"])
    return len(seen)


def on_site_technician_count(facility):
    seen = set()
    for deployment in aggregates.deployments_of_facility(facility["id"]):
        if deployment["status"] == "ON_SITE":
            seen.add(deployment["technician_id"])
    return len(seen)


def staging_counters(facility):
    occupied = aggregates.facility_staging_slots_occupied(facility["id"])
    slot_count = facility["staging_slot_count"]
    free = slot_count - occupied
    ratio = round_half_up(D(occupied) / D(slot_count), 4)
    return occupied, free, ratio


def recompute(facility):
    """Run the fixed-order posture recomputation and return the posture."""
    clock_date = clock.date()

    # step 0 — lazy permit expiry
    _expire_lapsed_permits(facility, clock_date)

    coverage = permit_coverage_ok(facility, clock_date)
    licensed_on_site = on_site_licensed_technician_count(facility, clock_date)
    occupied, free, _ratio = staging_counters(facility)

    # step 1 — posture, by the first matching condition
    if facility["status"] == "DEMOBILIZED":
        posture = "FROZEN"
    elif not coverage:
        posture = "FROZEN"
        if facility["status"] == "COMMISSIONED":
            facility["status"] = "SUSPENDED"
            touch(facility)
    else:
        if facility["status"] == "SUSPENDED":
            # coverage restored: SUSPENDED -> COMMISSIONED, commissioned_at untouched
            facility["status"] = "COMMISSIONED"
            touch(facility)
        if facility["status"] == "SETUP":
            posture = "RESTRICTED"
        elif free == 0:
            posture = "RESTRICTED"
        elif licensed_on_site == 0:
            posture = "RESTRICTED"
        else:
            posture = "OPEN"

    facility["posture"] = posture
    return posture


def recompute_for_facility_id(facility_id):
    facility = db.facilities.get(facility_id)
    if facility is not None:
        recompute(facility)
    return facility


def recompute_all():
    for facility in list(db.facilities.values()):
        recompute(facility)


def recompute_for_vehicle(vehicle):
    if vehicle is not None:
        recompute_for_facility_id(vehicle["facility_id"])


def recompute_for_event(storm_event_id):
    for facility in aggregates.facilities_of_event(storm_event_id):
        recompute(facility)
