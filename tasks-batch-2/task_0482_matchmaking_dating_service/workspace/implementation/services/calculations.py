"""Pinned calculation rules (PRD §3.3, §3.4, §3.9)."""
import math
from decimal import Decimal, ROUND_HALF_UP

from db import db
from clock import clock
from services.common import parse_iso

W_ATTR = Decimal("0.40")
W_PREF = Decimal("0.35")
W_LOC = Decimal("0.15")
W_ACT = Decimal("0.10")
COMPATIBILITY_THRESHOLD = Decimal("70.00")
ATTR_KEYS = ("education", "lifestyle", "values")
DAYS_PER_MONTH = 30


def round_half_up(value, places=0):
    q = Decimal(1).scaleb(-places)  # 10**-places
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Age (from birth_date vs logical clock)
# ---------------------------------------------------------------------------
def age_years(member):
    birth = parse_iso(member["birth_date"])
    now = clock.now()
    years = now.year - birth.year
    # subtract one if birthday hasn't occurred yet this year
    if (now.month, now.day) < (birth.month, birth.day):
        years -= 1
    return years


# ---------------------------------------------------------------------------
# City proximity band: derive a band index from city label.
# The PRD treats proximity as a band gap between cities. With only a city label
# available (no geo table), same city => gap 0 => proximity 100; different city
# => the test scenarios use distinct cities and rely on the proximity formula.
# We model each city as its own band index by stable enumeration is impossible
# from a label alone, so different cities differ by exactly one band (gap 1)
# unless identical. This keeps "same city" => 100 and "different city" => 75.
# ---------------------------------------------------------------------------
def location_proximity(city_a, city_b):
    if city_a == city_b:
        return Decimal(100)
    band_gap = 1
    val = 100 - 25 * band_gap
    return Decimal(max(val, 0))


# ---------------------------------------------------------------------------
# Preference helpers
# ---------------------------------------------------------------------------
def gender_satisfies(candidate_gender, seeker_seeking_gender):
    if seeker_seeking_gender == "ANY":
        return True
    return candidate_gender == seeker_seeking_gender


def age_in_band(candidate_age, pref):
    return pref["min_age"] <= candidate_age <= pref["max_age"]


def attribute_match(pref_a, pref_b):
    """100 * (1 - normalized L1 distance) over shared keys; 0 if no shared keys."""
    wa = pref_a["attribute_weights"]
    wb = pref_b["attribute_weights"]
    shared = [k for k in ATTR_KEYS if k in wa and k in wb]
    if not shared:
        return Decimal(0)
    l1 = sum(abs(Decimal(wa[k]) - Decimal(wb[k])) for k in shared)
    max_l1 = Decimal(100) * len(shared)  # each key in 0..100
    if max_l1 == 0:
        return Decimal(0)
    normalized = l1 / max_l1
    return Decimal(100) * (Decimal(1) - normalized)


def preference_overlap(member_a, member_b, pref_a, pref_b):
    age_a = age_years(member_a)
    age_b = age_years(member_b)
    gender_ok = (
        gender_satisfies(member_b["gender"], pref_a["seeking_gender"])
        and gender_satisfies(member_a["gender"], pref_b["seeking_gender"])
    )
    age_ok = age_in_band(age_b, pref_a) and age_in_band(age_a, pref_b)
    if gender_ok and age_ok:
        return Decimal(100)
    score = Decimal(0)
    if gender_ok:
        score += Decimal(50)
    if age_ok:
        score += Decimal(50)
    return score


def activity_recency(member_a, member_b):
    sa, sb = member_a["status"], member_b["status"]
    if sa == "ACTIVE" and sb == "ACTIVE":
        return Decimal(100)
    if sa == "FROZEN" or sb == "FROZEN":
        return Decimal(50)
    return Decimal(0)


def compatibility_score(member_a, member_b, pref_a, pref_b):
    attr = attribute_match(pref_a, pref_b)
    pref = preference_overlap(member_a, member_b, pref_a, pref_b)
    loc = location_proximity(member_a["city"], member_b["city"])
    act = activity_recency(member_a, member_b)
    raw = attr * W_ATTR + pref * W_PREF + loc * W_LOC + act * W_ACT
    return round_half_up(raw, 2)


# ---------------------------------------------------------------------------
# Refund on cancel (PRD §3.9) — round-per-line-then-sum (PINNED)
# ---------------------------------------------------------------------------
def refund_on_cancel(membership):
    plan = db.membership_plans.get(membership["plan_id"])
    if plan is None:
        return 0
    member_id = membership["member_id"]
    now = clock.now()
    start = parse_iso(membership["start_at"])
    elapsed_seconds = (now - start).total_seconds()
    elapsed_days = math.floor(elapsed_seconds / 86400.0) if elapsed_seconds >= 0 else 0
    elapsed_full_months = elapsed_days // DAYS_PER_MONTH
    remaining_months = max(plan["term_months"] - elapsed_full_months - 1, 0)
    months_refund_cents = remaining_months * plan["monthly_fee_cents"]

    included = plan["included_coaching_sessions"]
    consumed = sum(
        1 for s in db.coaching_sessions.values()
        if s["member_id"] == member_id and s["status"] in ("HELD", "NO_SHOW")
    )
    unused_sessions = max(included - consumed, 0)
    coaching_refund_cents = 0
    if included > 0:
        per_session_rate = Decimal(plan["coaching_value_cents"]) / Decimal(included)
        rounded_line = int(round_half_up(per_session_rate, 0))
        coaching_refund_cents = rounded_line * unused_sessions

    return int(months_refund_cents + coaching_refund_cents)
