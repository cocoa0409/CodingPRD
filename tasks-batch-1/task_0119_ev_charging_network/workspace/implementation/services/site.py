"""Site load balancing + aggregates (PRD §3.1, §3.4; calculation site_load_allocation).

The cap is demand_charge_threshold_kw when demand_avoidance_armed else
circuit_limit_kw. Candidate set = the site's sessions with charging_status ==
CHARGING. Each candidate requests min(stall.max_power_kw, cap). PROPORTIONAL
splits pro-rata then truncates to 0.1 kW and distributes the leftover by
(stall.reservation_priority ASC, created_at ASC). PRIORITY fills a strict
waterfall in the same sort order. sum(allocated) <= cap always.
"""
from decimal import Decimal

import db
from validation import floor_to_tenth

GRANULARITY = Decimal("0.1")


def _charging_candidates(site_id):
    """Sessions on this site with charging_status == CHARGING, with their stall."""
    out = []
    for s in db.sessions.values():
        if s["charging_status"] != "CHARGING":
            continue
        st = db.stalls.get(s["stall_id"])
        if st is None or st["site_id"] != site_id:
            continue
        out.append((s, st))
    return out


def _cap(site):
    if site["demand_avoidance_armed"]:
        return Decimal(str(site["demand_charge_threshold_kw"]))
    return Decimal(str(site["circuit_limit_kw"]))


def _sort_key(pair):
    # priority ASC, then created_at ASC (creation order via _seq as a stable
    # tiebreaker when timestamps tie under a frozen test clock)
    s, st = pair
    return (st["reservation_priority"], s["created_at"], s["_seq"])


def run_allocation(site, trigger_reason):
    """Run a load-balance pass, write allocated_power_kw to CHARGING sessions
    (0 to all others on the site is handled by callers/state transitions), and
    record a LoadAllocation snapshot. Returns the snapshot record.
    """
    cap = _cap(site)
    candidates = _charging_candidates(site["id"])
    candidates.sort(key=_sort_key)

    # Each candidate's request.
    requests = []
    for s, st in candidates:
        req = min(Decimal(str(st["max_power_kw"])), cap)
        requests.append(req)
    sum_req = sum(requests, Decimal("0"))

    allocations = [Decimal("0")] * len(candidates)

    if site["allocation_policy"] == "PROPORTIONAL":
        if sum_req <= cap:
            for i in range(len(candidates)):
                allocations[i] = requests[i]
        else:
            # pro-rata raw share, truncated to 0.1 kW
            for i in range(len(candidates)):
                raw = cap * requests[i] / sum_req
                allocations[i] = floor_to_tenth(raw)
            # distribute leftover in 0.1 kW units by (priority ASC, created_at ASC)
            allocated_sum = sum(allocations, Decimal("0"))
            leftover = cap - allocated_sum
            # number of whole 0.1 units available
            units = int((leftover / GRANULARITY).to_integral_value(rounding="ROUND_FLOOR"))
            # candidates already sorted by (priority, created_at). A candidate
            # cannot exceed its own request.
            idx = 0
            n = len(candidates)
            # iterate giving one unit at a time, capped at request, in sorted order
            guard = 0
            while units > 0 and n > 0:
                progressed = False
                for i in range(n):
                    if units <= 0:
                        break
                    if allocations[i] + GRANULARITY <= requests[i]:
                        allocations[i] += GRANULARITY
                        units -= 1
                        progressed = True
                if not progressed:
                    break
                guard += 1
                if guard > 100000:
                    break
    else:  # PRIORITY waterfall
        remaining = cap
        for i in range(len(candidates)):
            grant = min(requests[i], remaining)
            allocations[i] = grant
            remaining -= grant

    # Write back to sessions.
    allocated_total = Decimal("0")
    session_count = 0
    for i, (s, st) in enumerate(candidates):
        alloc = allocations[i]
        s["allocated_power_kw"] = alloc
        if alloc > 0:
            session_count += 1
        allocated_total += alloc

    # Update site aggregates.
    site["allocated_total_kw"] = allocated_total

    snap = {
        "site_id": site["id"],
        "trigger_reason": trigger_reason,
        "policy_used": site["allocation_policy"],
        "cap_kw": cap,
        "allocated_total_kw": allocated_total,
        "session_count": session_count,
    }
    db.stamp_create(snap)
    db.load_allocations[snap["id"]] = snap
    return snap


def recompute_site_aggregates(site):
    """Recompute allocated_total_kw (sum over CHARGING sessions' allocated_power_kw)
    and active_session_count (PREPARING/CHARGING/SUSPENDED) without a rebalance.
    """
    total = Decimal("0")
    active = 0
    for s in db.sessions.values():
        st = db.stalls.get(s["stall_id"])
        if st is None or st["site_id"] != site["id"]:
            continue
        if s["charging_status"] == "CHARGING":
            total += Decimal(str(s["allocated_power_kw"]))
        if s["charging_status"] in ("PREPARING", "CHARGING", "SUSPENDED"):
            active += 1
    site["allocated_total_kw"] = total
    site["active_session_count"] = active
