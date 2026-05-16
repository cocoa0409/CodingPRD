"""Capacity ledger reconciliation and standby promotion selector.

Per PRD §2.8 the seat counters on every TestCenterCapacity row are computed,
not client-supplied. After every Registration insert or status change tied to
a given (test_event_id, test_center_id), the ledger is reconciled in full.

§3.4 describes the standby_promotion_priority selector: fill accommodation
seats first, then general seats, ranked by (priority_class, registered_at,
Candidate.id).
"""

from typing import Optional

import db
from clock import now
from response import iso_utc_ms, parse_iso_utc


def find_capacity_row(test_event_id: str, test_center_id: str) -> Optional[dict]:
    for cap in db.test_center_capacities.all():
        if cap["test_event_id"] == test_event_id and cap["test_center_id"] == test_center_id:
            return cap
    return None


def reconcile_capacity(test_event_id: str, test_center_id: str) -> Optional[dict]:
    """Recompute the four computed counters from Registration rows.

    Returns the capacity row (or None if no row exists for the pair).
    """
    cap = find_capacity_row(test_event_id, test_center_id)
    if cap is None:
        return None

    confirmed = 0
    accommodation_used = 0
    standby = 0
    for r in db.registrations.all():
        if r["test_event_id"] != test_event_id or r["test_center_id"] != test_center_id:
            continue
        if r["status"] in ("CONFIRMED", "CHECKED_IN", "COMPLETED"):
            confirmed += 1
            if r.get("accommodation_required"):
                accommodation_used += 1
        elif r["status"] == "STANDBY":
            standby += 1

    cap["confirmed_seats_used"] = confirmed
    cap["accommodation_seats_used"] = accommodation_used
    cap["standby_seats_pending"] = standby
    cap["available_seats"] = cap["total_capacity"] - confirmed
    db.touch(cap)
    return cap


def try_promote_to_confirmed(reg: dict, cap: dict) -> bool:
    """If the row is STANDBY and there is capacity, flip it to CONFIRMED.

    Updates the registration's status and recomputes its fee snapshot
    (no late fee added on promotion). Caller is responsible for reconciling
    the capacity row afterwards.
    """
    if reg["status"] != "STANDBY":
        return False
    accommodation_required = reg.get("accommodation_required", False)
    # General capacity must have free seat (compare against current confirmed count + 1)
    if cap["available_seats"] <= 0:
        return False
    if accommodation_required:
        # Must have free accommodation seat too.
        if (cap["accommodation_capacity"] - cap["accommodation_seats_used"]) <= 0:
            return False
    reg["status"] = "CONFIRMED"
    db.touch(reg)
    return True


def _eligible_standby_pool(test_event_id: str, test_center_id: str):
    """Collect STANDBY rows whose standby_promotion_eligibility_at <= now()."""
    current_now = now()
    pool = []
    for r in db.registrations.all():
        if r["test_event_id"] != test_event_id or r["test_center_id"] != test_center_id:
            continue
        if r["status"] != "STANDBY":
            continue
        eligibility = r.get("standby_promotion_eligibility_at")
        if eligibility:
            try:
                elig_dt = parse_iso_utc(eligibility)
            except Exception:
                elig_dt = current_now
            if elig_dt > current_now:
                continue
        pool.append(r)
    return pool


def _ranking_key(r: dict, priority_class: int):
    return (priority_class, parse_iso_utc(r["registered_at"]), r["candidate_id"])


def standby_promotion_selector(
    test_event_id: str,
    test_center_id: str,
    seats_freed: int = None,
    accommodation_seats_freed: int = 0,
) -> int:
    """Waterfall standby promotion per PRD §3.4.

    Inputs:
      seats_freed (N): total seats freed by the triggering event. When
        omitted (e.g., a generic post-mutation sweep), the selector
        falls back to current `available_seats` as N and a conservative
        K=0 — only class 0 promotions land in that fallback path.
      accommodation_seats_freed (K): accommodation-seat subset of N
        (K <= N). Determines how many phase-1 accommodation slots
        exist before spill.

    Step 1 (phase 1): fill K accommodation slots from S_accommodation
      (class 0). Acc-required candidates also need acc-capacity left
      on the cap row; the per-iteration acc capacity check enforces
      that. If S_accommodation runs out before K, the unfilled count
      K_unused spills into phase 2.
    Step 2 (phase 2): fill (N - K) pure general slots from class 2
      candidates only (S_general), plus K_unused spilled slots which
      both class 1 (S_accommodation) and class 2 may consume — sorted
      by the ranking key (class, registered_at, candidate_id).

    Returns the number of promotions performed.
    """
    cap = find_capacity_row(test_event_id, test_center_id)
    if cap is None:
        return 0
    cap = reconcile_capacity(test_event_id, test_center_id)
    if cap is None:
        return 0

    # If the caller didn't tell us how many seats were freed, derive a
    # safe fallback: N = current available_seats. We can't tell what
    # subset is accommodation-typed, so set K=0 (phase 1 skipped). This
    # keeps the "no info" path safe for callers that don't yet track
    # what was freed.
    if seats_freed is None:
        seats_freed = max(0, cap["available_seats"])
        accommodation_seats_freed = 0

    N = max(0, int(seats_freed))
    K = max(0, min(int(accommodation_seats_freed), N))
    if N == 0:
        reconcile_capacity(test_event_id, test_center_id)
        return 0

    promotions = 0

    # ---- Phase 1: fill K accommodation slots with class-0 candidates.
    phase1_filled = 0
    while phase1_filled < K:
        cap = reconcile_capacity(test_event_id, test_center_id)
        if cap is None:
            break
        # Must still have free general AND free accommodation capacity.
        if cap["available_seats"] <= 0:
            break
        if (cap["accommodation_capacity"] - cap["accommodation_seats_used"]) <= 0:
            break
        pool = _eligible_standby_pool(test_event_id, test_center_id)
        acc_pool = [r for r in pool if r.get("accommodation_required")]
        if not acc_pool:
            break
        chosen = min(acc_pool, key=lambda r: _ranking_key(r, 0))
        chosen["status"] = "CONFIRMED"
        db.touch(chosen)
        promotions += 1
        phase1_filled += 1
    K_unused = K - phase1_filled

    # ---- Phase 2: fill (N - K) + K_unused general slots.
    # The (N - K) pure-general slots cannot back accommodation candidates;
    # only class 2 may take them. The K_unused spilled slots still have
    # acc-capacity behind them, so class 1 may take them (and class 2
    # may also).
    pure_general_slots = N - K
    spilled_slots = K_unused

    # Fill spilled slots first by priority key (class 1 < class 2).
    while spilled_slots > 0:
        cap = reconcile_capacity(test_event_id, test_center_id)
        if cap is None:
            break
        if cap["available_seats"] <= 0:
            break
        pool = _eligible_standby_pool(test_event_id, test_center_id)
        if not pool:
            break
        # In the spilled-slot subphase, class 1 (acc-required) may
        # promote only if there is still free accommodation capacity
        # to back them.
        acc_room = (cap["accommodation_capacity"] - cap["accommodation_seats_used"]) > 0
        candidates = []
        for r in pool:
            if r.get("accommodation_required"):
                if acc_room:
                    candidates.append((_ranking_key(r, 1), r))
            else:
                candidates.append((_ranking_key(r, 2), r))
        if not candidates:
            break
        candidates.sort(key=lambda t: t[0])
        chosen = candidates[0][1]
        chosen["status"] = "CONFIRMED"
        db.touch(chosen)
        promotions += 1
        spilled_slots -= 1

    # Now fill pure-general slots — class 2 only.
    while pure_general_slots > 0:
        cap = reconcile_capacity(test_event_id, test_center_id)
        if cap is None:
            break
        if cap["available_seats"] <= 0:
            break
        pool = _eligible_standby_pool(test_event_id, test_center_id)
        class2 = [r for r in pool if not r.get("accommodation_required")]
        if not class2:
            break
        chosen = min(class2, key=lambda r: _ranking_key(r, 2))
        chosen["status"] = "CONFIRMED"
        db.touch(chosen)
        promotions += 1
        pure_general_slots -= 1

    reconcile_capacity(test_event_id, test_center_id)
    return promotions
