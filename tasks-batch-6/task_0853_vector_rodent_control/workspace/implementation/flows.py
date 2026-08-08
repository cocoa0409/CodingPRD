"""Shared cascades and state transitions used by more than one route module."""

import aggregates
import calc
import lclock
import store


def zone_recompute(zone_id, counters=True, index=True):
    return aggregates.recompute_zone_by_id(zone_id, counters=counters, index=index)


# --- complaint ----------------------------------------------------------


def close_complaint(complaint, status, reason):
    """A system or administrative closure; the zone loses an open case."""
    complaint["status"] = status
    complaint["closure_reason"] = reason
    complaint["closed_at"] = lclock.now()
    store.touch(complaint)
    zone_recompute(complaint["zone_id"])
    return complaint


def originating_complaint(order):
    """The complaint the order was issued from (via its originating visit)."""
    inspection = store.inspections.get(order["inspection_id"])
    if inspection is None:
        return None
    return store.complaints.get(inspection["complaint_id"])


# --- property -----------------------------------------------------------


def qualifying_assessments(property_id, now):
    """Assessments feeding the REVIEWED chronic score (PRD 3.4)."""
    rows = []
    for assessment in store.assessments.values():
        inspection = store.inspections.get(assessment["inspection_id"])
        if inspection is None:
            continue
        if inspection["property_id"] != property_id:
            continue
        if inspection["status"] != "COMPLETED" or inspection["result"] != "VIOLATION_FOUND":
            continue
        if not calc.in_chronic_lookback(inspection["completed_at"], now):
            continue
        rows.append((inspection["completed_at"], assessment["created_at"],
                     assessment["_seq"], assessment["infestation_index"]))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    return [(r[3], r[0]) for r in rows]


def recompute_chronic_reviewed(prop):
    """Cascade hops 3 and 4 of the inspection-completion chain (PRD 3.5)."""
    now = lclock.now()
    qualifying = qualifying_assessments(prop["id"], now)
    score, flag = calc.chronic_score_reviewed(qualifying, now)
    was_flagged = prop["chronic_flag"]
    prop["chronic_score"] = score
    prop["chronic_flag"] = flag
    store.bump(prop)
    if flag and not was_flagged:
        zone = store.zones.get(prop["zone_id"])
        if zone is not None:
            aggregates.zone_counters(zone)
            aggregates.zone_index(zone)
            store.bump(zone)
    return prop


def refresh_property_counters(prop, bump_version=False):
    aggregates.property_counters(prop)
    if bump_version:
        store.bump(prop)
    else:
        store.touch(prop)
    return prop


# --- abatement order ----------------------------------------------------


def order_reaches_terminal(order, status):
    """COMPLIED or CLOSED: the parcel loses an open order and the case resolves."""
    order["status"] = status
    order["closed_at"] = lclock.now()
    store.touch(order)
    prop = store.properties.get(order["property_id"])
    if prop is not None:
        refresh_property_counters(prop, bump_version=True)
    complaint = originating_complaint(order)
    if complaint is not None and complaint["status"] == "ABATEMENT_ORDERED":
        close_complaint(complaint, "CLOSED_RESOLVED", "RESOLVED")
    return order


def serve_order(order, served_at):
    """Move an order into SERVED and derive its compliance deadline."""
    prop = store.properties.get(order["property_id"])
    zone = store.zones.get(prop["zone_id"]) if prop is not None else None
    posture = zone["posture"] if zone is not None else "NORMAL"
    order["status"] = "SERVED"
    order["served_at"] = served_at
    order["compliance_deadline"] = calc.abatement_compliance_deadline(
        served_at,
        order["infestation_tier_at_issue"],
        posture,
        order["escalation_level"],
        order["extension_days_total"],
    )
    store.bump(order)
    return order


# --- invoice ------------------------------------------------------------


def release_lien(invoice):
    if invoice["lien_status"] != "FILED":
        return invoice
    invoice["lien_status"] = "RELEASED"
    prop = store.properties.get(invoice["property_id"])
    if prop is not None:
        aggregates.property_counters(prop)
        store.touch(prop)
    return invoice


def owner_recompute(owner_id):
    return aggregates.recompute_owner_by_id(owner_id)
