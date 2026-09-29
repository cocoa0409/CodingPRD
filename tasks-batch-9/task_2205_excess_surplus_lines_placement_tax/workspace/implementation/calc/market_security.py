"""Calculation: market_security_score (PRD 3.2).

Integer points throughout, no rounding anywhere, score floored at zero.
"""

import store

RATING_POINTS = {
    "A_PLUS_PLUS": 40,
    "A_PLUS": 35,
    "A": 30,
    "A_MINUS": 25,
    "B_PLUS_PLUS": 15,
    "B_PLUS": 10,
    "NR": 0,
}

CAPITAL_TIER_1_CENTS = 5000000000
CAPITAL_TIER_2_CENTS = 1500000000
CAPITAL_TIER_3_CENTS = 500000000
CAPITAL_TIER_FLOOR_POINTS = 5
ALIEN_TRUST_MIN_CENTS = 540000000
DRIFT_MULTIPLIER = 2
APPROVE_MIN_SCORE = 70
CONDITION_MIN_SCORE = 50

DECISION_STATUS = {
    "APPROVE": "APPROVED",
    "CONDITION": "CONDITIONAL",
    "DECLINE": "DECLINED",
}


def rating_points(rating):
    return RATING_POINTS.get(rating, 0)


def capital_tier_points(cents):
    cents = int(cents or 0)
    if cents >= CAPITAL_TIER_1_CENTS:
        return 40
    if cents >= CAPITAL_TIER_2_CENTS:
        return 30
    if cents >= CAPITAL_TIER_3_CENTS:
        return 20
    return CAPITAL_TIER_FLOOR_POINTS


def latest_approved_review(carrier_id):
    """The carrier's APPROVED review with the greatest created_at."""
    approved = [r for r in store.reviews_of_carrier(carrier_id)
                if r.get("status") == "APPROVED"]
    if not approved:
        return None
    return approved[-1]


def compute(carrier):
    """Returns (variant_applied, score)."""
    rate_pts = rating_points(carrier.get("am_best_rating"))
    cap_pts = capital_tier_points(carrier.get("capital_surplus_cents"))

    if carrier.get("domicile_type") == "ALIEN":
        trust_pts = 15 if int(carrier.get("trust_fund_cents") or 0) >= ALIEN_TRUST_MIN_CENTS else 0
    else:
        trust_pts = 15

    listing_pts = 5 if carrier.get("naic_quarterly_listing") else 0

    base = rate_pts + cap_pts + trust_pts + listing_pts

    prior = latest_approved_review(carrier["id"])
    if prior is None:
        return "INITIAL_REVIEW", base

    prior_subscore = (rating_points(prior.get("rating_at_review"))
                      + capital_tier_points(prior.get("capital_surplus_at_review_cents")))
    current_subscore = rate_pts + cap_pts
    drift_penalty = max(0, prior_subscore - current_subscore) * DRIFT_MULTIPLIER
    return "RECERTIFICATION", max(0, base - drift_penalty)


def decision_matches_band(decision, score):
    score = int(score or 0)
    if decision == "APPROVE":
        return score >= APPROVE_MIN_SCORE
    if decision == "CONDITION":
        return CONDITION_MIN_SCORE <= score < APPROVE_MIN_SCORE
    if decision == "DECLINE":
        return score < CONDITION_MIN_SCORE
    return False
