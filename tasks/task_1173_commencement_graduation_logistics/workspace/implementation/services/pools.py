"""effective_capacity_and_pools + ticket_pool_waterfall + promotion scan (scaffold §1.3)."""
import math

import db
from services.honor import HONOR_RANK

NON_TERMINAL_ALLOC = {"PENDING", "ALLOCATED", "PARTIAL", "WAITLISTED"}


def effective_venue(ceremony):
    if ceremony["weather_mode"] == "RAIN_PLAN_ACTIVE":
        return db.venues.get(ceremony["rain_venue_id"])
    return db.venues.get(ceremony["venue_id"])


def recompute_ceremony_pools(ceremony):
    """Recompute effective_capacity, open_seat_count, ticket_pool_total, ticket_pool_remaining."""
    venue = effective_venue(ceremony)
    if venue is None:
        ceremony["effective_capacity"] = 0
    else:
        ceremony["effective_capacity"] = venue["total_capacity"]

    assigned = sum(
        1 for s in db.seat_assignments.values()
        if s["ceremony_id"] == ceremony["id"] and s["status"] == "ASSIGNED"
    )
    ceremony["open_seat_count"] = ceremony["effective_capacity"] - assigned

    ceremony["ticket_pool_total"] = math.floor(
        ceremony["effective_capacity"] * float(ceremony["ticket_ratio"])
    )

    granted_sum = sum(
        a["granted_count"] for a in db.ticket_allocations.values()
        if a["ceremony_id"] == ceremony["id"] and a["status"] in NON_TERMINAL_ALLOC
    )
    ceremony["ticket_pool_remaining"] = ceremony["ticket_pool_total"] - granted_sum


def entitlement_for(ceremony, grad):
    base = ceremony["guest_ticket_base_cap"]
    if grad["honor_tier"] != "NONE":
        base += ceremony["honor_bonus_tickets"]
    return base


def waterfall_order_key(alloc):
    """honor_rank DESC, requested_count DESC, allocation.created_at ASC (never id)."""
    grad = db.graduates.get(alloc["graduate_id"])
    rank = HONOR_RANK.get(grad["honor_tier"], 0) if grad else 0
    return (-rank, -alloc["requested_count"], alloc["created_at"])


def run_waterfall_final(ceremony):
    """FINAL waterfall variant. Mutates allocations and the ceremony pool.
    Returns (processed_count, granted_total, waitlisted_count)."""
    in_scope = [
        a for a in db.ticket_allocations.values()
        if a["ceremony_id"] == ceremony["id"]
        and a["status"] in NON_TERMINAL_ALLOC
        and a["requested_count"] >= 1
    ]
    for a in in_scope:
        a["granted_count"] = 0
        a["waitlist_position"] = None

    # pool_remaining based on pool_total (grants all reset to zero)
    pool_remaining = ceremony["ticket_pool_total"]

    in_scope.sort(key=waterfall_order_key)

    processed = 0
    granted_total = 0
    waitlisted = 0
    waitlist_pos = 0
    for a in in_scope:
        grad = db.graduates[a["graduate_id"]]
        ent = entitlement_for(ceremony, grad)
        a["entitlement_count"] = ent
        target = min(a["requested_count"], ent)
        grant = min(target, pool_remaining)
        pool_remaining -= grant
        a["granted_count"] = grant
        granted_total += grant
        processed += 1
        if grant == target:
            a["status"] = "ALLOCATED"
            a["waitlist_position"] = None
        elif grant > 0:
            a["status"] = "PARTIAL"
            a["waitlist_position"] = None
        else:
            a["status"] = "WAITLISTED"
            waitlist_pos += 1
            a["waitlist_position"] = waitlist_pos
            waitlisted += 1
        db.touch(a)
        # waterfall run is a mutation of the allocation
        a["version"] += 1

    ceremony["ticket_pool_remaining"] = pool_remaining
    return processed, granted_total, waitlisted


def run_promotion_scan(ceremony):
    """Top up unsatisfied (PARTIAL, WAITLISTED) allocations in waterfall order."""
    unsatisfied = [
        a for a in db.ticket_allocations.values()
        if a["ceremony_id"] == ceremony["id"] and a["status"] in {"PARTIAL", "WAITLISTED"}
        and a["requested_count"] >= 1
    ]
    unsatisfied.sort(key=waterfall_order_key)
    pool_remaining = ceremony["ticket_pool_remaining"]
    for a in unsatisfied:
        if pool_remaining <= 0:
            break
        grad = db.graduates[a["graduate_id"]]
        ent = entitlement_for(ceremony, grad)
        a["entitlement_count"] = ent
        target = min(a["requested_count"], ent)
        gap = target - a["granted_count"]
        if gap <= 0:
            continue
        top_up = min(gap, pool_remaining)
        pool_remaining -= top_up
        a["granted_count"] += top_up
        if a["granted_count"] >= target:
            a["status"] = "ALLOCATED"
            a["waitlist_position"] = None
        else:
            a["status"] = "PARTIAL"
            a["waitlist_position"] = None
        db.touch(a)
        a["version"] += 1

    # Re-rank waitlist positions among remaining WAITLISTED in waterfall order
    remaining_wl = [
        a for a in db.ticket_allocations.values()
        if a["ceremony_id"] == ceremony["id"] and a["status"] == "WAITLISTED"
    ]
    remaining_wl.sort(key=waterfall_order_key)
    for idx, a in enumerate(remaining_wl, start=1):
        if a["waitlist_position"] != idx:
            a["waitlist_position"] = idx
            db.touch(a)

    ceremony["ticket_pool_remaining"] = pool_remaining


def provisional_estimate(ceremony, grad, requested_count):
    """PROVISIONAL variant at request time: min(requested, entitlement, current pool_remaining). Non-mutating."""
    ent = entitlement_for(ceremony, grad)
    recompute_ceremony_pools(ceremony)
    return max(0, min(requested_count, ent, ceremony["ticket_pool_remaining"]))
