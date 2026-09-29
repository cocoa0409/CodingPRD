"""Shared domain helpers: audit/version bookkeeping, seat inventory,
readiness posture, ledgers and the cross-entity cascades."""

import json
from contextlib import contextmanager

from calc import (demand_band_of, fill_bp_of, donor_level_of,
                  renewal_priority_score)
from db import clock_year, db, iso, new_id, now, now_iso

# --------------------------------------------------------------------------
# audit fields / version bookkeeping (PRD 2.4)
# --------------------------------------------------------------------------

_AUDIT = ("updated_at", "version")


def base_fields():
    return {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }


def serialize(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


def _snapshot(record):
    payload = {k: v for k, v in record.items()
               if not k.startswith("_") and k not in _AUDIT}
    return json.dumps(payload, sort_keys=True, default=str)


def _bumped():
    """Ids already version-bumped during the current request.  A cascade that
    touches one resource in several hops still leaves a single version trail."""
    try:
        from flask import g
        if not hasattr(g, "_bumped_ids"):
            g._bumped_ids = set()
        return g._bumped_ids
    except Exception:
        return set()


def bump(record):
    record["version"] += 1
    record["updated_at"] = now_iso()


def force_bump(record):
    """Unconditional single version increment (used where the specification
    says a resource's version increments even though nothing else changed)."""
    bumped = _bumped()
    if record["id"] in bumped:
        record["updated_at"] = now_iso()
        return
    bumped.add(record["id"])
    bump(record)


@contextmanager
def touch(record):
    """Increment version / refresh updated_at only when something actually
    changed inside the block -- refreshing a derived counter counts."""
    before = _snapshot(record)
    yield record
    if _snapshot(record) != before:
        bumped = _bumped()
        if record["id"] in bumped:
            record["updated_at"] = now_iso()
        else:
            bumped.add(record["id"])
            bump(record)


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------

def season_of_concert(concert):
    return db.seasons.get(concert["season_id"])


def agreement_for_season(season_id):
    for agreement in db.agreements.values():
        if agreement["season_id"] == season_id:
            return agreement
    return None


def concerts_of_season(season_id):
    return [c for c in db.concerts.values() if c["season_id"] == season_id]


def contracts_of_concert(concert_id):
    return [c for c in db.contracts.values() if c["concert_id"] == concert_id]


def services_of_concert(concert_id):
    return [s for s in db.services.values() if s["concert_id"] == concert_id]


def engagements_of_service(service_id):
    return [e for e in db.engagements.values() if e["service_id"] == service_id]


def created_key(record):
    return (record["created_at"], record["_seq"])


def concert_program_key(concert):
    return (concert["_perf_start_dt"], concert["created_at"], concert["_seq"])


def service_schedule_key(service):
    return (service["_sched_start_dt"], service["created_at"], service["_seq"])


def inventory_element(concert, seat_section_id):
    for element in concert["section_inventory"]:
        if element["seat_section_id"] == seat_section_id:
            return element
    return None


# --------------------------------------------------------------------------
# seat inventory as a conserved quantity (PRD 2.9)
# --------------------------------------------------------------------------

def recompute_inventory(concert):
    """Re-establish held/sold/available/fill/demand from the live claims and
    refresh the concert's two roll-ups."""
    concert_id = concert["id"]
    orders = list(db.orders.values())
    packages = list(db.packages.values())
    for element in concert["section_inventory"]:
        section_id = element["seat_section_id"]
        held = 0
        sold = 0
        for order in orders:
            if order["concert_id"] != concert_id or order["seat_section_id"] != section_id:
                continue
            if order["status"] == "HELD":
                held += order["seat_count"]
            elif order["status"] == "PAID":
                sold += order["seat_count"]
        for package in packages:
            if package["seat_section_id"] != section_id:
                continue
            if concert_id not in package["concert_ids"]:
                continue
            if package["status"] == "PENDING_PAYMENT":
                held += package["seat_count"]
            elif package["status"] in ("ACTIVE", "EXPIRED"):
                sold += package["seat_count"]
        element["held_count"] = held
        element["sold_count"] = sold
        element["available_count"] = element["capacity"] - held - sold
        element["fill_bp"] = fill_bp_of(held + sold, element["capacity"])
        element["demand_band"] = demand_band_of(element["fill_bp"])
    concert["seats_held_count"] = sum(e["held_count"] for e in concert["section_inventory"])
    concert["seats_sold_count"] = sum(e["sold_count"] for e in concert["section_inventory"])


def refresh_concerts(concert_ids):
    for concert_id in concert_ids:
        concert = db.concerts.get(concert_id)
        if concert is None:
            continue
        with touch(concert):
            recompute_inventory(concert)


def available_seats(concert, seat_section_id):
    element = inventory_element(concert, seat_section_id)
    if element is None:
        return 0
    return element["available_count"]


# --------------------------------------------------------------------------
# readiness posture (PRD 2.7)
# --------------------------------------------------------------------------

def compute_readiness(concert):
    season = season_of_concert(concert)
    season_status = season["status"] if season else None
    if season_status in ("SINGLE_ON_SALE", "IN_PROGRESS"):
        for contract in contracts_of_concert(concert["id"]):
            if contract["status"] in ("OFFERED", "COUNTERED"):
                return "BLOCKED"
    for service in services_of_concert(concert["id"]):
        if service["status"] == "PUBLISHED" and service["compliance_status"] == "UNDERSTAFFED":
            return "AT_RISK"
    return "READY"


def recompute_readiness(concert):
    """Assign the freshly computed posture (caller owns the touch())."""
    concert["readiness_posture"] = compute_readiness(concert)


# --------------------------------------------------------------------------
# programming promotion / unlock (PRD 3.2)
# --------------------------------------------------------------------------

def try_promote_lock(concert):
    if concert["programming_status"] != "PROGRAMMED":
        return
    contracts = contracts_of_concert(concert["id"])
    if not contracts:
        return
    if not all(c["status"] in ("SIGNED", "WITHDRAWN") for c in contracts):
        return
    if not any(c["status"] == "SIGNED" for c in contracts):
        return
    if not any(s["status"] == "PUBLISHED" for s in services_of_concert(concert["id"])):
        return
    concert["programming_status"] = "LOCKED"


def unlock_programming(concert):
    if concert["programming_status"] == "LOCKED":
        concert["programming_status"] = "PROGRAMMED"


# --------------------------------------------------------------------------
# patron ledgers (PRD 2.10, 3.4)
# --------------------------------------------------------------------------

def recompute_patron_score(patron):
    patron["renewal_priority_score"] = renewal_priority_score(patron, clock_year())


def apply_donation(patron, amount_cents):
    patron["lifetime_donation_cents"] += amount_cents
    patron["donor_level"] = donor_level_of(patron["lifetime_donation_cents"])
    recompute_patron_score(patron)


# --------------------------------------------------------------------------
# subscription package roll-up
# --------------------------------------------------------------------------

def recompute_fulfilled(package):
    count = 0
    for concert_id in package["concert_ids"]:
        concert = db.concerts.get(concert_id)
        if concert is not None and concert["performance_status"] != "CANCELLED":
            count += 1
    package["fulfilled_concert_count"] = count
