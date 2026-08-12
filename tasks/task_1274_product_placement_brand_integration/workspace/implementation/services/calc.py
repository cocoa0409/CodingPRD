"""Calculation rules per SCAFFOLD 1.3 / PRD 3."""
from decimal import Decimal, ROUND_HALF_UP

import db
import util


def _D(x):
    return Decimal(str(x))


def round_half_up_cents(x):
    """Round a Decimal-compatible number to whole cents, half-up; returns int."""
    return int(_D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---- constants ----
MAKEGOOD_MULTIPLIER = Decimal("1.5")
BONUS_CAP_PCT = Decimal("0.25")
VALUE_RATE_CENTS_PER_SECOND = Decimal("7.5")
VERBAL_MISS_PENALTY_CENTS = 5000
SEVERE_SHORTFALL_RATIO = Decimal("0.5")
SEVERE_SURCHARGE = Decimal("1.2")
MAKEGOOD_PROMO_PENALTY = 1
PROXIMITY_SCORE = 40
WATCHLIST_SCORE = 30
STRICT_DENY_THRESHOLD = 40
STANDARD_DENY_THRESHOLD = 60

IN_FLIGHT_PROPOSAL_STATUSES = {"DRAFT", "PRODUCTION_REVIEW", "NETWORK_REVIEW",
                               "REVISION_REQUESTED", "APPROVED"}
HELD_CONTRACT_STATUSES = {"PENDING_SIGNATURE", "ACTIVE", "UNDER_VERIFICATION",
                          "MAKEGOOD_REQUIRED", "SETTLED"}


# ---- brief_budget_remaining ----

def recompute_brief_remaining(brief_id):
    brief = db.briefs.get(brief_id)
    if brief is None:
        return
    remaining = brief["budget_cents"]
    for p in db.proposals.values():
        if p["brief_id"] == brief_id and p["status"] in IN_FLIGHT_PROPOSAL_STATUSES:
            remaining -= p["proposed_fee_cents"]
    for c in db.contracts.values():
        prop = db.proposals.get(c["proposal_id"])
        if prop and prop["brief_id"] == brief_id and c["status"] in HELD_CONTRACT_STATUSES:
            remaining -= c["base_fee_cents"]
    brief["remaining_budget_cents"] = remaining


# ---- contract_billing_value: provisional variant ----

def provisional_value_cents(base_fee_cents, guaranteed_seconds, rate_cents_per_second,
                            estimated_exposure_seconds):
    shortfall = max(0, guaranteed_seconds - estimated_exposure_seconds)
    deduction = round_half_up_cents(_D(shortfall) * _D(rate_cents_per_second) * MAKEGOOD_MULTIPLIER)
    return base_fee_cents - deduction


# ---- measured_exposure_valuation ----

def measured_exposure(segments):
    """Returns (measured_seconds, measured_value_cents).

    PINNED ORDER: round each per-segment product to whole cents FIRST, then sum.
    measured_seconds is the unrounded sum.
    """
    measured_seconds = sum(segments)
    value = 0
    for s in segments:
        value += round_half_up_cents(_D(s) * VALUE_RATE_CENTS_PER_SECOND)
    return measured_seconds, value


# ---- bonus ----

def compute_bonus(base_fee_cents, guaranteed_seconds, rate_cents_per_second, measured_seconds):
    over = max(0, _D(measured_seconds) - _D(guaranteed_seconds))
    bonus = _D(BONUS_CAP_PCT) * _D(base_fee_cents)
    product = over * _D(rate_cents_per_second)
    raw = min(bonus, product)
    return round_half_up_cents(raw)


# ---- makegood_compensation ----

def compute_makegood(contract, measured_seconds, measured_verbal_mentions):
    """Returns (amount_cents, reason or None). Amount 0 => no credit."""
    guaranteed_seconds = contract["guaranteed_seconds"]
    shortfall_seconds = max(0, _D(guaranteed_seconds) - _D(measured_seconds))
    verbal_misses = max(0, contract["guaranteed_verbal_mentions"] - measured_verbal_mentions)
    if shortfall_seconds <= 0 and verbal_misses <= 0:
        return 0, None
    shortfall_ratio = shortfall_seconds / _D(guaranteed_seconds)
    raw = round_half_up_cents(shortfall_seconds * _D(contract["rate_cents_per_second"]) * MAKEGOOD_MULTIPLIER)
    raw = raw + verbal_misses * VERBAL_MISS_PENALTY_CENTS
    if shortfall_ratio >= SEVERE_SHORTFALL_RATIO:
        raw = round_half_up_cents(_D(raw) * SEVERE_SURCHARGE)
    amount = min(contract["base_fee_cents"], raw)
    if shortfall_seconds > 0 and verbal_misses > 0:
        reason = "COMBINED"
    elif shortfall_seconds > 0:
        reason = "EXPOSURE_SHORTFALL"
    else:
        reason = "VERBAL_MISS"
    return amount, reason


# ---- clearance_conflict_score ----

def _airdate_within_window(ep_a, ep_b, policy):
    """|air_date delta| in days within policy window. STRICT: <=7; STANDARD: <7."""
    delta_days = abs((util.parse_iso(ep_a["air_date"]) - util.parse_iso(ep_b["air_date"])).total_seconds()) / 86400.0
    if policy == "STRICT":
        return delta_days <= 7
    return delta_days < 7


def proximity_hit(episode, category):
    """Exists a same-category GRANTED clearance on another episode within this
    episode's series policy window."""
    series = db.series.get(episode["series_id"])
    policy = series["clearance_policy"] if series else "STANDARD"
    for cl in db.clearances.values():
        if cl["status"] != "GRANTED":
            continue
        if cl["episode_id"] == episode["id"]:
            continue
        if cl["category"] != category:
            continue
        other_ep = db.episodes.get(cl["episode_id"])
        if other_ep is None:
            continue
        if _airdate_within_window(episode, other_ep, policy):
            return True
    return False


def clearance_conflict_score(clearance):
    episode = db.episodes[clearance["episode_id"]]
    series = db.series.get(episode["series_id"])
    policy = series["clearance_policy"] if series else "STANDARD"
    brand = db.brands.get(clearance["brand_id"])
    score = 0
    if proximity_hit(episode, clearance["category"]):
        score += PROXIMITY_SCORE
    if brand and brand.get("watchlist_flag"):
        score += WATCHLIST_SCORE
    return score, policy


# ---- cross_promo_balance ----

def crosspromo_status(owed_count, fulfilled_count):
    if fulfilled_count == 0 and owed_count > 0:
        return "OWED"
    if fulfilled_count >= owed_count:
        return "FULFILLED"
    return "PARTIALLY_FULFILLED"
