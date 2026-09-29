"""Carrier scoring — PRD §3.1 (capability screening) and §3.2 (scorecards and the
composite score)."""
from decimal import Decimal

import store
from numeric import D, q2, q4, rnd

# --- capability screening constants (PRD §3.1) -------------------------------
FLEET_TARGET_UNITS = Decimal("200")
MODE_WEIGHT = Decimal("0.40")
FLEET_WEIGHT = Decimal("0.30")
INSURANCE_WEIGHT_CAP = Decimal("0.30")
CAPABILITY_PASS_FLOOR = Decimal("70.00")
MAX_REMEDIATIONS = 2

# --- scorecard constants (PRD §3.2) -----------------------------------------
NO_TENDER_ACCEPTANCE_DEFAULT_PCT = Decimal("100.00")
CLAIMS_PENALTY_MULTIPLIER = Decimal("1000")
SCORECARD_ON_TIME_WEIGHT = Decimal("0.45")
SCORECARD_ACCEPTANCE_WEIGHT = Decimal("0.35")
SCORECARD_CLAIMS_WEIGHT = Decimal("0.20")

# --- composite constants (PRD §3.2) -----------------------------------------
SCORECARD_LOOKBACK_COUNT = 3
FINAL_VARIANT_MIN_SCORECARDS = 1
RECENCY_WEIGHTS = (Decimal("0.50"), Decimal("0.30"), Decimal("0.20"))
PROVISIONAL_PERFORMANCE_BASELINE = Decimal("90.00")
PERFORMANCE_WEIGHT = Decimal("0.70")
CAPABILITY_WEIGHT = Decimal("0.20")
INSURANCE_WEIGHT = Decimal("0.10")
INSURANCE_HEADROOM_DAYS = 90
INSURANCE_FULL_SCORE = Decimal("100.00")
INSURANCE_THIN_SCORE = Decimal("60.00")
WATCHLIST_FLOOR = Decimal("75.00")

MODES = ("DRY_VAN", "REEFER", "FLATBED")


def capability_score(carrier, review):
    """PRD §3.1 — four inputs taken in order: mode coverage, fleet adequacy, insurance
    headroom, weighted total."""
    required = review["required_modes"]
    served = set(carrier["service_modes"])
    matched = sum(1 for mode in required if mode in served)
    mode_coverage = q2(D(matched) * Decimal("100.00") / D(len(required)))

    fleet = q2(D(carrier["fleet_power_units"]) * Decimal("100.00") / FLEET_TARGET_UNITS)
    if fleet > Decimal("100.00"):
        fleet = Decimal("100.00")

    auto_ratio = q4(D(carrier["auto_liability_limit_usd"]) / D(review["min_auto_liability_usd"]))
    if auto_ratio > Decimal("1.0000"):
        auto_ratio = Decimal("1.0000")
    cargo_ratio = q4(D(carrier["cargo_limit_usd"]) / D(review["min_cargo_usd"]))
    if cargo_ratio > Decimal("1.0000"):
        cargo_ratio = Decimal("1.0000")
    insurance = q2(Decimal("50.00") * auto_ratio + Decimal("50.00") * cargo_ratio)

    return q2(MODE_WEIGHT * mode_coverage + FLEET_WEIGHT * fleet
              + INSURANCE_WEIGHT_CAP * insurance)


def carrier_scorecards_in_lookback(carrier_id):
    """PUBLISHED and DISPUTED scorecards, period_end DESC then created_at ASC, capped
    at the three most recent."""
    rows = [s for s in store.scorecards.values()
            if s["carrier_id"] == carrier_id and s["status"] in ("PUBLISHED", "DISPUTED")]
    rows.sort(key=lambda s: (_neg_key(s["period_end"]), s["created_at"], s["_seq"]))
    return rows[:SCORECARD_LOOKBACK_COUNT]


def _neg_key(iso):
    """Sort key that orders an ISO instant descending inside an ascending sort."""
    return -store.parse_dt(iso).timestamp()


def scorecard_period_metrics(scorecard):
    """PRD §3.2 — select the period's tenders on the half-open window, derive tender
    acceptance, the claims subscore and the weighted composite."""
    carrier_id = scorecard["carrier_id"]
    start = store.parse_dt(scorecard["period_start"])
    end = store.parse_dt(scorecard["period_end"])
    record_ids = {r["id"] for r in store.rate_records.values()
                  if r["carrier_id"] == carrier_id}
    tenders = [t for t in store.tender_events.values()
               if t["rate_record_id"] in record_ids
               and start <= store.parse_dt(t["tendered_at"]) < end]
    count = len(tenders)
    if count == 0:
        acceptance = NO_TENDER_ACCEPTANCE_DEFAULT_PCT
    else:
        accepted = sum(1 for t in tenders if t["outcome"] == "ACCEPTED")
        acceptance = q2(D(accepted) * Decimal("100.00") / D(count))

    claims_subscore = q2(Decimal("100.00")
                         - D(scorecard["claims_ratio"]) * CLAIMS_PENALTY_MULTIPLIER)
    if claims_subscore < Decimal("0.00"):
        claims_subscore = Decimal("0.00")

    composite = q2(SCORECARD_ON_TIME_WEIGHT * D(scorecard["on_time_pct"])
                   + SCORECARD_ACCEPTANCE_WEIGHT * acceptance
                   + SCORECARD_CLAIMS_WEIGHT * claims_subscore)
    scorecard["period_tender_count"] = count
    scorecard["tender_acceptance_pct"] = acceptance
    scorecard["composite_score"] = composite
    return composite


def recompute_composite(carrier):
    """PRD §3.2 — assemble the lookback, choose the variant, derive the performance and
    insurance components and combine them."""
    kept = carrier_scorecards_in_lookback(carrier["id"])
    carrier["published_scorecard_count"] = len(kept)
    if len(kept) >= FINAL_VARIANT_MIN_SCORECARDS:
        variant = "FINAL_PERFORMANCE"
        weights = RECENCY_WEIGHTS[:len(kept)]
        weight_sum = sum(weights, Decimal("0"))
        total = sum((D(card["composite_score"]) * weight
                     for card, weight in zip(kept, weights)), Decimal("0"))
        performance = q2(total / weight_sum)
    else:
        variant = "PROVISIONAL_SCREENING"
        performance = PROVISIONAL_PERFORMANCE_BASELINE

    expiry = store.dt_of(carrier["insurance_expiry_date"])
    threshold = store.now() + store.days(INSURANCE_HEADROOM_DAYS)
    insurance = INSURANCE_FULL_SCORE if expiry >= threshold else INSURANCE_THIN_SCORE

    carrier["composite_score"] = q2(PERFORMANCE_WEIGHT * performance
                                    + CAPABILITY_WEIGHT * D(carrier["capability_score"])
                                    + INSURANCE_WEIGHT * insurance)
    carrier["composite_score_variant"] = variant
    return carrier["composite_score"]


def reevaluate_standing(carrier):
    """PRD §3.2 link 3 — the watchlist floor is re-read after every publication."""
    score = D(carrier["composite_score"])
    if carrier["status"] == "QUALIFIED" and score < WATCHLIST_FLOOR:
        carrier["status"] = "WATCHLIST"
        carrier["status_reason"] = "SCORECARD_BELOW_FLOOR"
    elif carrier["status"] == "WATCHLIST" and score >= WATCHLIST_FLOOR:
        carrier["status"] = "QUALIFIED"
        carrier["status_reason"] = None
