"""Shared pledge reservation logic (used by pledge create and crisis resolve)."""
from store import db, stamp_new, touch

# pledge_type -> the FundingPool.program_component it must draw from (§3.6).
PLEDGE_TYPE_COMPONENT = {
    "HEATING": "HEATING",
    "COOLING": "COOLING",
    "CRISIS": "CRISIS",
    "RECONNECTION": "CRISIS",
    "ARREARAGE": "HEATING",
}


def periods_overlap(a_start, a_end, b_start, b_end):
    """Closed-interval overlap: share any instant/day counts (§3.6)."""
    return a_start <= b_end and b_start <= a_end


def account_has_period_overlap(utility_account_id, start_dt, end_dt, exclude_id=None):
    for pl in db.pledges.values():
        if pl["id"] == exclude_id:
            continue
        if pl["utility_account_id"] != utility_account_id:
            continue
        if pl["status"] not in ("PLEDGED", "PAID"):
            continue
        other_start = pl.get("_bp_start_dt")
        other_end = pl.get("_bp_end_dt")
        if other_start is None or other_end is None:
            continue
        if periods_overlap(start_dt, end_dt, other_start, other_end):
            return True
    return False


def create_pledge(pool, fields, bp_start_dt=None, bp_end_dt=None):
    """Persist a PLEDGED pledge and bump the owning pool's version (reservation)."""
    pledge = dict(fields)
    pledge["status"] = "PLEDGED"
    pledge["_bp_start_dt"] = bp_start_dt
    pledge["_bp_end_dt"] = bp_end_dt
    stamp_new(pledge)
    db.pledges[pledge["id"]] = pledge
    # Reserving draws on the pool: reserved_cents rises (derived) and version bumps.
    touch(pool)
    return pledge
