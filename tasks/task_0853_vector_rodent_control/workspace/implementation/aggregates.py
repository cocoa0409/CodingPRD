"""Aggregate recomputation (PRD 2.7: always recomputed from scratch)."""

import datetime

import calc
import lclock
import store


# --- zone ---------------------------------------------------------------


def zone_counters(zone):
    """The zone's three counters -- no time window applies (PRD 3.8)."""
    zid = zone["id"]
    zone["open_complaint_count"] = sum(
        1
        for c in store.complaints.values()
        if c["zone_id"] == zid and c["status"] not in calc.CLOSED_COMPLAINT_STATUSES
    )
    zone["chronic_property_count"] = sum(
        1 for p in store.properties.values() if p["zone_id"] == zid and p["chronic_flag"]
    )
    zone["active_station_count"] = sum(
        1
        for s in store.stations.values()
        if s["zone_id"] == zid and s["status"] in ("ACTIVE", "DAMAGED")
    )
    store.touch(zone)
    return zone


def zone_index_components(zone):
    """Evaluate calculation zone_rodent_index against the current clock."""
    now = lclock.now()
    window_start = now - datetime.timedelta(days=calc.SURVEILLANCE_WINDOW_DAYS)
    zid = zone["id"]
    eligible = [
        s
        for s in store.stations.values()
        if s["zone_id"] == zid and s["status"] in ("ACTIVE", "DAMAGED")
    ]
    eligible_ids = set(s["id"] for s in eligible)
    window_readings = [
        r
        for r in store.readings.values()
        if r["bait_station_id"] in eligible_ids
        and window_start <= r["reading_at"] <= now
    ]
    open_complaints = [
        c
        for c in store.complaints.values()
        if c["zone_id"] == zid
        and c["status"] in calc.OPEN_COMPLAINT_STATUSES
        and window_start <= c["created_at"] <= now
    ]
    result = calc.zone_rodent_index(window_readings, open_complaints, now)
    result["eligible_station_count"] = len(eligible)
    return result


def zone_index(zone):
    """Refresh rodent_index / posture / last_index_recomputed_at."""
    result = zone_index_components(zone)
    previous_posture = zone["posture"]
    zone["rodent_index"] = result["rodent_index"]
    zone["posture"] = result["posture"]
    zone["last_index_recomputed_at"] = lclock.now()
    if result["posture"] != previous_posture:
        store.bump(zone)
    else:
        store.touch(zone)
    return result


def zone_full(zone):
    """Counters and index together."""
    zone_counters(zone)
    return zone_index(zone)


def zone_of(zone_id):
    return store.zones.get(zone_id)


def recompute_zone_by_id(zone_id, counters=True, index=True):
    zone = store.zones.get(zone_id)
    if zone is None:
        return None
    if counters:
        zone_counters(zone)
    if index:
        zone_index(zone)
    return zone


# --- property -----------------------------------------------------------


def property_counters(prop):
    """open_order_count and lien_encumbered, recomputed from scratch."""
    pid = prop["id"]
    prop["open_order_count"] = sum(
        1
        for o in store.orders.values()
        if o["property_id"] == pid and o["status"] not in ("COMPLIED", "CLOSED")
    )
    prop["lien_encumbered"] = any(
        i["property_id"] == pid and i["lien_status"] == "FILED"
        for i in store.invoices.values()
    )
    return prop


# --- owner --------------------------------------------------------------


def owner_aggregates(owner):
    """outstanding_balance_cents and lifetime_paid_cents (PRD 3.7)."""
    oid = owner["id"]
    owner["outstanding_balance_cents"] = sum(
        i["balance_due_cents"]
        for i in store.invoices.values()
        if i["owner_id"] == oid and i["billing_status"] in ("APPROVED", "PARTIALLY_PAID")
    )
    owner["lifetime_paid_cents"] = sum(
        i["amount_paid_cents"]
        for i in store.invoices.values()
        if i["owner_id"] == oid
        and i["billing_status"] in ("APPROVED", "PARTIALLY_PAID", "PAID")
    )
    store.touch(owner)
    return owner


def recompute_owner_by_id(owner_id):
    owner = store.owners.get(owner_id)
    if owner is not None:
        owner_aggregates(owner)
    return owner
