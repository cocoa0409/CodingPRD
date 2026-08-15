"""Core serializers + computed-field recomputation + shared business helpers."""

from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
from db import db

# ---- constants from scaffold calculations ----
VIABILITY_PASS_PCT = Decimal("70.00")
LOAN_DAYS = 21
OVERDUE_SUSPENSION_THRESHOLD = 3
LOT_MAX_PACKETS = 200
DECAY_HALF_LIFE_DAYS = 90
TIER_TRUSTED_MIN_TERMINALS = 5
TIER_TRUSTED_RATE = Decimal("0.90")
TIER_PROBATION_MIN_TERMINALS = 3
TIER_PROBATION_RATE = Decimal("0.60")
LIMIT_BY_TIER = {"PROBATION": 2, "STANDARD": 5, "TRUSTED": 8}
BASE_CREDIT = {"SEED_PACKET": 2, "PLANT_START": 5, "CUTTING": 3}
CONDITION_MULT = {"EXCELLENT": Decimal("1.5"), "GOOD": Decimal("1.0"), "FAIR": Decimal("0.5")}
RARITY_BONUS = 2
MAX_CREDITS_PER_MEMBER_EVENT = 25


def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)


# ============================ lot helpers ============================

def effective_viability(lot):
    if lot.get("final_viability_pct") is not None:
        return Decimal(str(lot["final_viability_pct"]))
    return Decimal(str(lot["provisional_viability_pct"]))


def compute_viable_seed_count(lot):
    eff = effective_viability(lot)
    v = (Decimal(lot["seeds_remaining"]) * eff / Decimal(100))
    return int(v.to_integral_value(rounding="ROUND_FLOOR"))


def lot_view(lot):
    out = {k: v for k, v in lot.items() if not k.startswith("_")}
    out["viable_seed_count"] = compute_viable_seed_count(lot)
    # final_viability_pct / provisional at 2dp formatting as number
    if out.get("final_viability_pct") is not None:
        out["final_viability_pct"] = float(round_half_up(out["final_viability_pct"], 2))
    out["provisional_viability_pct"] = float(round_half_up(out["provisional_viability_pct"], 2))
    return out


def check_lot_depleted(lot):
    """Auto-transition ACTIVE -> DEPLETED after pack/void mutations."""
    if lot["status"] != "ACTIVE":
        return
    if lot["seeds_remaining"] != 0:
        return
    for p in db.packets.values():
        if p["lot_id"] == lot["id"] and p["status"] == "AVAILABLE":
            return
    lot["status"] = "DEPLETED"
    db.touch(lot)


# ============================ member recomputation ============================

NON_TERMINAL_CHECKOUT = {"ACTIVE", "OVERDUE", "RETURNED", "DISPUTED"}


def member_checkouts(member_id):
    return [c for c in db.checkouts.values() if c["member_id"] == member_id]


def recompute_member(member, bump_version=False):
    """Recompute counters, rates, tier, limit, credit totals for a member.

    Overdue count is maintained incrementally by sweep/verify/write-off; we
    recompute everything from the checkout set + ledger for correctness.
    """
    cks = member_checkouts(member["id"])
    active = sum(1 for c in cks if c["status"] in NON_TERMINAL_CHECKOUT)
    overdue = sum(1 for c in cks if c["status"] == "OVERDUE")
    terminal = [c for c in cks if c["status"] in ("VERIFIED", "WRITTEN_OFF")]
    terminal_count = len(terminal)
    verified = sum(1 for c in cks if c["status"] == "VERIFIED")

    member["active_checkout_count"] = active
    member["overdue_checkout_count"] = overdue
    member["terminal_checkout_count"] = terminal_count
    member["verified_return_count"] = verified

    # simple_return_rate: 4dp half-up
    if terminal_count == 0:
        rate = Decimal("0.0")
    else:
        rate = (Decimal(verified) / Decimal(terminal_count)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP)
    member["simple_return_rate"] = float(rate)

    # decay_weighted_return_score
    if terminal_count == 0:
        score = Decimal("0.0")
    else:
        now = db.now()
        num = Decimal("0")
        den = Decimal("0")
        for c in terminal:
            due = c["_due_at_dt"]
            delta_seconds = max(0.0, (now - due).total_seconds())
            days = Decimal(str(delta_seconds)) / Decimal(86400)
            exponent = days / Decimal(DECAY_HALF_LIFE_DAYS)
            # w = 0.5 ** exponent
            w = Decimal(2) ** (-exponent)
            outcome = Decimal(1) if c["status"] == "VERIFIED" else Decimal(0)
            num += w * outcome
            den += w
        if den == 0:
            score = Decimal("0.0")
        else:
            score = (num / den).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    member["decay_weighted_return_score"] = float(score)

    # tier + limit from the ROUNDED 4dp simple rate
    if terminal_count >= TIER_TRUSTED_MIN_TERMINALS and rate >= TIER_TRUSTED_RATE:
        tier = "TRUSTED"
    elif terminal_count >= TIER_PROBATION_MIN_TERMINALS and rate < TIER_PROBATION_RATE:
        tier = "PROBATION"
    else:
        tier = "STANDARD"
    member["standing_tier"] = tier
    member["effective_borrow_limit"] = LIMIT_BY_TIER[tier]

    # credit ledger totals
    entries = [e for e in db.credit_entries.values() if e["member_id"] == member["id"]]
    earned = sum(e["credits"] for e in entries if e["entry_type"] == "EARNED")
    redeemed = sum(e["credits"] for e in entries if e["entry_type"] == "REDEEMED")
    expired = sum(e["credits"] for e in entries if e["entry_type"] == "EXPIRED")
    revoked = sum(e["credits"] for e in entries if e["entry_type"] == "REVOKED")
    member["credits_earned_total"] = earned
    member["credits_redeemed_total"] = redeemed
    member["credits_expired_total"] = expired
    member["credits_revoked_total"] = revoked
    member["credits_balance"] = earned - redeemed - expired - revoked

    if bump_version:
        db.touch(member)
    return member


def member_view(member):
    recompute_member(member)
    return {k: v for k, v in member.items() if not k.startswith("_")}


# ============================ swap credit valuation ============================

def per_item_credit(item_type, condition, rarity_flag):
    base = Decimal(BASE_CREDIT[item_type])
    mult = CONDITION_MULT[condition]
    product = base * mult
    rounded = int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if rarity_flag:
        rounded += RARITY_BONUS
    return rounded


def earned_at_event(member_id, event_id):
    return sum(e["credits"] for e in db.credit_entries.values()
               if e["member_id"] == member_id and e["event_id"] == event_id
               and e["entry_type"] == "EARNED")


def redeemed_at_event(member_id, event_id):
    return sum(e["credits"] for e in db.credit_entries.values()
               if e["member_id"] == member_id and e["event_id"] == event_id
               and e["entry_type"] == "REDEEMED")


# ============================ overlap checks ============================

def event_buffered_overlap(site_id, start_dt, end_dt, exclude_event_id=None):
    """Half-open buffered interval [start-30m, end+30m) intersection."""
    from datetime import timedelta as td
    bs = start_dt - td(minutes=30)
    be = end_dt + td(minutes=30)
    for ev in db.events.values():
        if ev["site_id"] != site_id:
            continue
        if ev["status"] == "CANCELLED":
            continue
        if exclude_event_id and ev["id"] == exclude_event_id:
            continue
        obs = ev["_start_dt"] - td(minutes=30)
        obe = ev["_end_dt"] + td(minutes=30)
        if bs < obe and obs < be:
            return True
    return False


def session_overlap(site_id, start_dt, end_dt, exclude_session_id=None):
    """Half-open [start, end) overlap for packing sessions at one site."""
    for s in db.sessions.values():
        if s["site_id"] != site_id:
            continue
        if s["status"] == "CANCELLED":
            continue
        if exclude_session_id and s["id"] == exclude_session_id:
            continue
        if start_dt < s["_end_dt"] and s["_start_dt"] < end_dt:
            return True
    return False


def volunteer_double_booked(volunteer_id, new_start, new_end, exclude_assignment_id=None):
    """Closed-interval semantics across volunteer's live (SIGNUP/ATTENDED) assignments."""
    for a in db.assignments.values():
        if a["volunteer_id"] != volunteer_id:
            continue
        if a["status"] not in ("SIGNUP", "ATTENDED"):
            continue
        if exclude_assignment_id and a["id"] == exclude_assignment_id:
            continue
        s = db.sessions.get(a["session_id"])
        if s is None:
            continue
        # closed-interval touch: conflict iff not (new_end < s.start or new_start > s.end)
        if not (new_end < s["_start_dt"] or new_start > s["_end_dt"]):
            return True
    return False
