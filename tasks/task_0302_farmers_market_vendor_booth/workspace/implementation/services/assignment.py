"""Booth assignment allocation engine: fee calc (§3.4), reservation, waitlist
ranking (§3.3), promotion, completion, cancellation, weather refund (§3.6)."""
from common import touch, round_half_up, floor_div, created_sort
from db import db
from errors import err
from services import derived

SIZE_MULT = {"SINGLE": 100, "DOUBLE": 180, "CORNER": 150}


# ---------------------------------------------------------------------------
# Fee calculation (§3.4)
# ---------------------------------------------------------------------------
def compute_fee(assignment, market, booth):
    mult = SIZE_MULT[booth["size_class"]]
    if assignment["assignment_type"] == "SEASON":
        base = market["season_fee_cents"]
    else:
        base = market["daily_fee_cents"]
    return round_half_up(base * mult, 100)


# ---------------------------------------------------------------------------
# Slot occupancy (§3.3)
# ---------------------------------------------------------------------------
def season_slot_free(booth):
    """SEASON slot free iff booth OPEN and no RESERVED/ACTIVE (SEASON or DAILY)
    occupies it across the season window."""
    if booth["status"] != "OPEN":
        return False
    for a in db.booth_assignments.values():
        if a["booth_id"] == booth["id"] and a["status"] in ("RESERVED", "ACTIVE"):
            return False
    return True


def daily_slot_free(booth, market_day_id):
    """DAILY slot free iff no RESERVED/ACTIVE assignment (SEASON or DAILY)
    occupies the booth on that market day. A SEASON RESERVED/ACTIVE holds it
    across the whole window, so it blocks any day."""
    if booth["status"] == "OUT_OF_SERVICE":
        return False
    for a in db.booth_assignments.values():
        if a["booth_id"] != booth["id"] or a["status"] not in ("RESERVED", "ACTIVE"):
            continue
        if a["assignment_type"] == "SEASON":
            return False
        if a["assignment_type"] == "DAILY" and a["market_day_id"] == market_day_id:
            return False
    return True


def slot_free(assignment, booth):
    if assignment["assignment_type"] == "SEASON":
        return season_slot_free(booth)
    return daily_slot_free(booth, assignment["market_day_id"])


# ---------------------------------------------------------------------------
# Waitlist ranking (§3.3 / calculations.waitlist_rank)
# ---------------------------------------------------------------------------
def _waitlist_peers(assignment):
    """WAITLISTED assignments on the same booth (+ same market_day for DAILY)."""
    peers = []
    for a in db.booth_assignments.values():
        if a["status"] != "WAITLISTED":
            continue
        if a["booth_id"] != assignment["booth_id"]:
            continue
        if assignment["assignment_type"] == "DAILY":
            if a["assignment_type"] == "DAILY" and a["market_day_id"] == assignment["market_day_id"]:
                peers.append(a)
        else:
            if a["assignment_type"] == "SEASON":
                peers.append(a)
    return created_sort(peers)


def assign_waitlist_rank(assignment):
    """Compute rank = 1 + count of existing WAITLISTED peers (excluding self)."""
    peers = [a for a in _waitlist_peers(assignment) if a["id"] != assignment["id"]]
    assignment["waitlist_rank"] = len(peers) + 1


def rerank_waitlist(sample_assignment):
    """Re-number all WAITLISTED peers on a slot by created_at ASC, starting 1."""
    peers = _waitlist_peers(sample_assignment)
    for i, a in enumerate(peers, start=1):
        if a["waitlist_rank"] != i:
            a["waitlist_rank"] = i
            touch(a)


# ---------------------------------------------------------------------------
# RESERVE (lock fee + booth/market side effects)
# ---------------------------------------------------------------------------
def do_reserve(assignment, market, booth, bump_assignment_version=True):
    assignment["status"] = "RESERVED"
    assignment["waitlist_rank"] = None
    assignment["fee_charged_cents"] = compute_fee(assignment, market, booth)
    if bump_assignment_version:
        touch(assignment)
    if assignment["assignment_type"] == "SEASON":
        booth["status"] = "SEASON_HELD"
        booth["season_holder_assignment_id"] = assignment["id"]
        touch(booth)
    # Ledger sync: recompute and force the market version bump (§3.3).
    derived.recompute_market_fees(market, force_bump=True)


# ---------------------------------------------------------------------------
# Promote rank-1 waitlister on a freed slot (cascade target)
# ---------------------------------------------------------------------------
def promote_head_if_free(booth, market, assignment_just_freed):
    """After a holder frees a slot, promote the rank-1 WAITLISTED assignment
    for that slot to RESERVED. Returns the promoted assignment or None."""
    # Determine candidate waitlist set keyed on what was freed.
    candidates = []
    for a in db.booth_assignments.values():
        if a["status"] != "WAITLISTED" or a["booth_id"] != booth["id"]:
            continue
        if assignment_just_freed["assignment_type"] == "DAILY":
            # A freed DAILY slot can promote DAILY waitlisters on the same day.
            if a["assignment_type"] == "DAILY" and a["market_day_id"] == assignment_just_freed["market_day_id"]:
                candidates.append(a)
            elif a["assignment_type"] == "SEASON" and season_slot_free(booth):
                candidates.append(a)
        else:
            candidates.append(a)
    candidates = created_sort(candidates)
    for head in candidates:
        # Only promote if its slot is actually free and permit still OK.
        if not slot_free(head, booth):
            continue
        vendor = db.vendors.get(head["vendor_id"])
        window_date = _window_date(head, market)
        if not derived.vendor_permit_ok_for_date(vendor, window_date):
            continue
        do_reserve(head, market, booth)
        rerank_waitlist(head)
        return head
    return None


def _window_date(assignment, market):
    if assignment["assignment_type"] == "SEASON":
        return market["season_start_date"]
    md = db.market_days.get(assignment["market_day_id"])
    return md["market_date"] if md else market["season_start_date"]


# ---------------------------------------------------------------------------
# Free a booth held by a SEASON assignment leaving RESERVED/ACTIVE
# ---------------------------------------------------------------------------
def free_booth_if_season_holder(assignment, booth):
    if assignment["assignment_type"] == "SEASON" and booth.get("season_holder_assignment_id") == assignment["id"]:
        booth["status"] = "OPEN"
        booth["season_holder_assignment_id"] = None
        touch(booth)


# ---------------------------------------------------------------------------
# COMPLETE (§3.3)
# ---------------------------------------------------------------------------
def do_complete(assignment, bump_version=True):
    market = db.markets[assignment["market_id"]]
    booth = db.booths[assignment["booth_id"]]
    was_occupying = assignment["status"] in ("RESERVED", "ACTIVE")
    assignment["status"] = "COMPLETED"
    if bump_version:
        touch(assignment)
    if was_occupying:
        free_booth_if_season_holder(assignment, booth)
        # Recompute ledger now that the holder left {RESERVED, ACTIVE}.
        derived.recompute_market_fees(market, force_bump=True)
        # Promote rank-1 waitlister (cascade re-adds its fee + bumps version).
        promote_head_if_free(booth, market, assignment)


# ---------------------------------------------------------------------------
# CANCEL (§3.3) — manual or system
# ---------------------------------------------------------------------------
def do_cancel(assignment, weather=False, bump_version=True):
    market = db.markets[assignment["market_id"]]
    booth = db.booths[assignment["booth_id"]]
    prior = assignment["status"]
    was_occupying = prior in ("RESERVED", "ACTIVE")
    was_waitlisted = prior == "WAITLISTED"

    assignment["status"] = "CANCELLED"
    if bump_version:
        touch(assignment)

    if weather:
        assignment["fee_refunded_cents"] = compute_weather_refund(assignment, market)
        touch(assignment)

    if was_occupying:
        free_booth_if_season_holder(assignment, booth)
        derived.recompute_market_fees(market, force_bump=True)
        promote_head_if_free(booth, market, assignment)
    elif was_waitlisted:
        rerank_waitlist(assignment)

    if weather and was_occupying:
        # fee_refunded changed the (now-excluded) row; ensure ledger reflects it.
        derived.recompute_market_fees(market, force_bump=False)


# ---------------------------------------------------------------------------
# Weather refund (§3.6 / calculations.fee_refund)
# ---------------------------------------------------------------------------
def compute_weather_refund(assignment, market):
    if assignment["assignment_type"] == "DAILY":
        return assignment["fee_charged_cents"]
    # SEASON: prorated one-day share, floored.
    scheduled_days = sum(1 for d in db.market_days.values()
                         if d["market_id"] == market["id"] and d["status"] != "CANCELLED")
    denom = max(scheduled_days, 1)
    return floor_div(assignment["fee_charged_cents"], denom)
