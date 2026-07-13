"""Calculation rules (SCAFFOLD section 1.3 / PRD sections 2.7, 3.2, 3.6-3.8)."""

import math
from decimal import Decimal

import store
from store import rhu

D0 = Decimal("0")
D100 = Decimal("100")

# --- review_sentiment ------------------------------------------------------
POSITIVE_MIN_RATING = 4
NEGATIVE_MAX_RATING = 2


def review_sentiment(rating):
    if rating >= POSITIVE_MIN_RATING:
        return "POSITIVE"
    if rating <= NEGATIVE_MAX_RATING:
        return "NEGATIVE"
    return "NEUTRAL"


# --- listing_health_score --------------------------------------------------
SITE_WEIGHTS = {
    "GOOGLE": Decimal("0.5"),
    "YELP": Decimal("0.3"),
    "FACEBOOK": Decimal("0.2"),
}
STATE_FACTOR = {
    "CONNECTED": Decimal("1.0"),
    "PENDING_SYNC": Decimal("0.6"),
    "SYNC_FAILED": Decimal("0.3"),
    "DISCONNECTED": Decimal("0.0"),
}
STALE_GRACE_DAYS = 7
STALE_MAX_DAYS = 365
MAX_STALENESS_PENALTY = Decimal("30")


def _elapsed_days(start, end):
    """Whole (floored) days between two instants; never negative."""
    seconds = (end - start).total_seconds()
    if seconds <= 0:
        return 0
    return int(math.floor(seconds / 86400.0))


def _site_score(listing, location):
    if listing is None:
        return D0
    match = store.nap_match_count(listing)
    site_base = (Decimal(match) / Decimal(3)) * D100
    factor = STATE_FACTOR[listing["sync_state"]]
    if listing["last_synced_at"] is None:
        staleness_days = STALE_MAX_DAYS
    else:
        staleness_days = _elapsed_days(listing["last_synced_at"], store.now())
    penalty = min(MAX_STALENESS_PENALTY, Decimal(2) * Decimal(max(0, staleness_days - STALE_GRACE_DAYS)))
    raw = site_base * factor - penalty
    if raw < D0:
        raw = D0
    if raw > D100:
        raw = D100
    return raw


def listing_health_score(location):
    by_site = {}
    for li in store.listings.values():
        if li["location_id"] == location["id"]:
            by_site[li["site"]] = li
    total = D0
    for site, weight in SITE_WEIGHTS.items():
        total += weight * _site_score(by_site.get(site), location)
    return rhu(total, 2)


# --- location_reputation_score --------------------------------------------
RATING_WEIGHT = Decimal("60")
RESPONSE_WEIGHT = Decimal("25")
LISTING_WEIGHT = Decimal("15")
DECAY_PER_30_DAYS = Decimal("0.02")
DECAY_FLOOR = Decimal("0.5")


def location_reviews(location):
    return [r for r in store.reviews.values() if r["location_id"] == location["id"]]


def _score(avg_rating, response_rate, listing_health):
    rating_component = (avg_rating / Decimal(5)) * RATING_WEIGHT
    response_component = response_rate * RESPONSE_WEIGHT
    listing_component = (listing_health / D100) * LISTING_WEIGHT
    return rhu(rating_component + response_component + listing_component, 2)


def reputation_score_provisional(location):
    subset = [r for r in location_reviews(location)
              if r["moderation_state"] in ("UNVERIFIED", "VERIFIED")]
    if subset:
        avg = sum((Decimal(r["rating"]) for r in subset), D0) / Decimal(len(subset))
        responded = sum(1 for r in subset if r["response_state"] == "RESPONDED")
        rate = Decimal(responded) / Decimal(len(subset))
    else:
        avg = D0
        rate = D0
    return _score(avg, rate, location["listing_health_score"])


def _decay_weight(review):
    age_days = _elapsed_days(review["posted_at"], store.now())
    blocks = age_days // 30
    weight = Decimal(1) - DECAY_PER_30_DAYS * Decimal(blocks)
    return max(DECAY_FLOOR, weight)


def reputation_score_certified(location):
    subset = [r for r in location_reviews(location) if r["moderation_state"] == "VERIFIED"]
    if subset:
        weights = [_decay_weight(r) for r in subset]
        weight_sum = sum(weights, D0)
        if weight_sum == D0:
            avg = D0
        else:
            avg = sum((w * Decimal(r["rating"]) for w, r in zip(weights, subset)), D0) / weight_sum
        responded = sum(1 for r in subset if r["response_state"] == "RESPONDED")
        rate = Decimal(responded) / Decimal(len(subset))
    else:
        avg = D0
        rate = D0
    return _score(avg, rate, location["listing_health_score"])


# --- location_posture ------------------------------------------------------
POSTURE_MIN_SCORE = Decimal("60.00")
ESCALATION_POSTURE_LIMIT = 3
LISTING_MIN_HEALTH = Decimal("40.00")
MIN_REVIEWS_FOR_SCORE_GATE = 3


def derive_posture(location):
    if location["compliance_hold"]:
        return "FROZEN"
    score_predicate = (
        location["review_count"] >= MIN_REVIEWS_FOR_SCORE_GATE
        and location["reputation_score_provisional"] < POSTURE_MIN_SCORE
    )
    escalation_predicate = location["open_escalation_count"] >= ESCALATION_POSTURE_LIMIT
    listing_predicate = location["listing_health_score"] < LISTING_MIN_HEALTH
    if score_predicate or escalation_predicate or listing_predicate:
        return "RESTRICTED"
    return "OPEN"


# --- campaign_billing_cost -------------------------------------------------
BASE_RATE = {"SMS": Decimal("0.075"), "EMAIL": Decimal("0.012")}
TIER1_MAX_INDEX = 100
TIER2_MAX_INDEX = 500


def volume_discount(send_index):
    if send_index <= TIER1_MAX_INDEX:
        return Decimal("1.00")
    if send_index <= TIER2_MAX_INDEX:
        return Decimal("0.90")
    return Decimal("0.80")


BILLABLE_STATUSES = ("SENT", "DELIVERED", "CLICKED", "CONVERTED", "FAILED")


def unit_cost(channel, send_index):
    return rhu(BASE_RATE[channel] * volume_discount(send_index), 2)


def campaign_requests(campaign):
    return store.by_created([r for r in store.review_requests.values()
                             if r["campaign_id"] == campaign["id"]])


def billable_requests(campaign):
    return [r for r in campaign_requests(campaign) if r["status"] in BILLABLE_STATUSES]


def campaign_billing_cost(campaign):
    """Round each line first, then sum the rounded lines."""
    total = Decimal("0.00")
    for r in billable_requests(campaign):
        if r["unit_cost"] is not None:
            total += r["unit_cost"]
    return rhu(total, 2)


# --- campaign_conversion_rate ---------------------------------------------
ATTRIBUTION_DAYS = 14


def _in_window(anchor, instant, days=ATTRIBUTION_DAYS):
    from datetime import timedelta
    if anchor is None or instant is None:
        return False
    return anchor <= instant < anchor + timedelta(days=days)


def campaign_conversion_rates(campaign):
    denom_rows = billable_requests(campaign)
    denominator = len(denom_rows)
    if denominator == 0:
        return Decimal("0.00"), Decimal("0.00")

    by_id = {r["id"]: r for r in denom_rows}
    strict_num = 0
    for v in store.reviews.values():
        req = by_id.get(v["review_request_id"])
        if req is None:
            continue
        if v["moderation_state"] != "VERIFIED":
            continue
        if _in_window(req["sent_at"], v["posted_at"]):
            strict_num += 1

    broad_num = 0
    activated_at = campaign["activated_at"]
    if activated_at is not None:
        for v in store.reviews.values():
            if v["location_id"] != campaign["location_id"]:
                continue
            if v["moderation_state"] not in ("UNVERIFIED", "VERIFIED"):
                continue
            if _in_window(activated_at, v["posted_at"]):
                broad_num += 1

    strict = min(Decimal("100.00"), rhu(Decimal(strict_num) / Decimal(denominator) * D100, 2))
    broad = min(Decimal("100.00"), rhu(Decimal(broad_num) / Decimal(denominator) * D100, 2))
    return strict, broad


# --- nps_score -------------------------------------------------------------
NPS_PROMOTER_MIN = 9
NPS_DETRACTOR_MAX = 6


def nps_category(score):
    if score >= NPS_PROMOTER_MIN:
        return "PROMOTER"
    if score <= NPS_DETRACTOR_MAX:
        return "DETRACTOR"
    return "PASSIVE"


def location_nps_score(location):
    submitted = [s for s in store.surveys.values()
                 if s["location_id"] == location["id"] and s["status"] == "SUBMITTED"]
    if not submitted:
        return Decimal("0.00")
    total = Decimal(len(submitted))
    promoters = Decimal(sum(1 for s in submitted if s["nps_score"] >= NPS_PROMOTER_MIN))
    detractors = Decimal(sum(1 for s in submitted if s["nps_score"] <= NPS_DETRACTOR_MAX))
    return rhu(promoters / total * D100 - detractors / total * D100, 2)


# --- competitor_benchmark --------------------------------------------------
def competitor_benchmark(location):
    rows = [c for c in store.competitors.values() if c["location_id"] == location["id"]]
    if not rows:
        return {
            "competitor_avg_rating": Decimal("0.00"),
            "rating_delta": rhu(location["avg_rating"], 2),
            "review_volume_delta": location["review_count"],
        }
    count = Decimal(len(rows))
    avg = rhu(sum((c["avg_rating"] for c in rows), D0) / count, 2)
    mean_volume = sum(c["review_count"] for c in rows) / len(rows)
    return {
        "competitor_avg_rating": avg,
        "rating_delta": rhu(location["avg_rating"] - avg, 2),
        "review_volume_delta": location["review_count"] - int(math.floor(mean_volume)),
    }
