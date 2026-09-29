"""Calculation rules (PRD sections 3.2, 3.3, 3.5, 3.6, 3.8)."""
from datetime import timedelta

import clock
import db
from errors import err
from util import (ceil_div, floor_div, median_half_up, round_half_up,
                  whole_days_between)

# ---- match_confidence_score constants (PRD 3.2)
CONF_W_IDENTIFIER = "0.55"
CONF_W_ATTRIBUTE = "0.30"
CONF_W_IMAGE = "0.15"
IDENTIFIER_ANCHOR_MIN_SCORE = 90
IDENTIFIER_ANCHOR_BONUS_BP = 500
LOW_IMAGE_SCORE_THRESHOLD = 50
LOW_IMAGE_CONFIDENCE_CEILING_BP = 6000
GRADE_EXACT_MIN_BP = 8500
GRADE_CLOSE_MIN_BP = 6000

# ---- effective_competitor_price constants (PRD 3.3)
OBSERVATION_TTL_HOURS = 72
OBSERVATION_PROXIMITY_MINUTES = 60
MATCH_DRIFT_ALERT_BP = 1200
COMPETITOR_STALE_SHARE_LIMIT_BP = 5000

# ---- price_index / posture constants (PRD 3.5)
MIN_INDEX_CONFIDENCE_BP = 7000
PERCEPTION_AGREEMENT_BP = 200
POSTURE_RESTRICTED_MULTIPLIER = 1
POSTURE_FROZEN_MULTIPLIER = 2

# ---- price_match_honored_price constants (PRD 3.8)
BEAT_BONUS_TIER1_MAX_CENTS = 2000
BEAT_BONUS_TIER2_MAX_CENTS = 10000
BEAT_BONUS_CAP_CENTS = 500

# ---- loop ceilings
MAX_MATCH_REVIEW_ROUNDS = 3
MAX_CLAIM_EVIDENCE_ROUNDS = 2

# ---- printer buffer (PRD 3.10)
PRINTER_BUFFER_MINUTES = 45


# =========================================================== match confidence

def match_confidence(match_method, identifier_score, attribute_score, image_score):
    """Returns (confidence_bp, confidence_variant, match_grade)."""
    blend_bp = round_half_up(
        100 * (_w(CONF_W_IDENTIFIER) * identifier_score
               + _w(CONF_W_ATTRIBUTE) * attribute_score
               + _w(CONF_W_IMAGE) * image_score))
    if match_method == "IDENTIFIER" and identifier_score >= IDENTIFIER_ANCHOR_MIN_SCORE:
        variant = "IDENTIFIER_ANCHORED"
        anchored_bp = identifier_score * 100 + IDENTIFIER_ANCHOR_BONUS_BP
        confidence_bp = min(10000, max(anchored_bp, blend_bp))
    else:
        variant = "ATTRIBUTE_BLEND"
        if image_score < LOW_IMAGE_SCORE_THRESHOLD:
            confidence_bp = min(blend_bp, LOW_IMAGE_CONFIDENCE_CEILING_BP)
        else:
            confidence_bp = min(10000, blend_bp)
    confidence_bp = max(0, min(10000, confidence_bp))
    if confidence_bp >= GRADE_EXACT_MIN_BP:
        grade = "EXACT"
    elif confidence_bp >= GRADE_CLOSE_MIN_BP:
        grade = "CLOSE"
    else:
        grade = "WEAK"
    return confidence_bp, variant, grade


def _w(literal):
    from util import dec
    return dec(literal)


# ================================================= effective competitor price

def link_observations(link_id):
    return [o for o in db.ordered(db.observations) if o["link_id"] == link_id]


def qualifying_observations(link_id):
    """PRD 3.3: ACTIVE, in stock, observed_at inside (now - 72h, now] inclusive."""
    instant = clock.now()
    floor_instant = instant - timedelta(hours=OBSERVATION_TTL_HOURS)
    return [o for o in link_observations(link_id)
            if o["status"] == "ACTIVE" and o["in_stock"] is True
            and o["observed_at"] <= instant and o["observed_at"] >= floor_instant]


def elect_effective_price(link):
    """Re-run the effective-price election on a link; returns True when changed."""
    product = db.products.get(link["product_id"])
    candidates = qualifying_observations(link["id"])
    candidates.sort(key=lambda o: (o["observed_price_cents"],
                                   -o["observed_at"].timestamp(),
                                   o["created_at"], o["_seq"]))
    before = (link.get("latest_effective_price_cents"),
              link.get("selected_observation_id"), link.get("data_status"),
              link.get("gap_bp"), link.get("gap_stale"))
    if not candidates:
        link["latest_effective_price_cents"] = None
        link["selected_observation_id"] = None
        link["data_status"] = "INSUFFICIENT"
        link["gap_bp"] = None
        link["gap_stale"] = False
    else:
        winner = candidates[0]
        link["latest_effective_price_cents"] = winner["observed_price_cents"]
        link["selected_observation_id"] = winner["id"]
        link["data_status"] = "SUFFICIENT"
        link["gap_bp"] = round_half_up(product["own_price_cents"] * 10000,
                                       winner["observed_price_cents"])
        link["gap_stale"] = False
    after = (link.get("latest_effective_price_cents"),
             link.get("selected_observation_id"), link.get("data_status"),
             link.get("gap_bp"), link.get("gap_stale"))
    return before != after


# ================================================== competitor drift counters

def competitor_links(competitor_id):
    return [l for l in db.ordered(db.links) if l["competitor_id"] == competitor_id]


def confirmed_match_count(competitor_id):
    return len([l for l in db.links.values()
                if l["competitor_id"] == competitor_id and l["status"] == "CONFIRMED"])


def stale_match_count(competitor_id):
    return len([l for l in db.links.values()
                if l["competitor_id"] == competitor_id and l["status"] == "CONFIRMED"
                and l.get("gap_stale") is True])


def stale_share_bp(competitor_id):
    confirmed = confirmed_match_count(competitor_id)
    if confirmed == 0:
        return 0
    return round_half_up(stale_match_count(competitor_id) * 10000, confirmed)


# ======================================================= product hard floor

def effective_floor_cents(product):
    from util import dec
    margin_derived = ceil_div(product["unit_cost_cents"],
                              dec(1) - dec(product["margin_floor_pct"]))
    return max(margin_derived, product["map_floor_cents"])


def price_change_count(product_id):
    return len([o for o in db.orders.values()
                if o["product_id"] == product_id and o["status"] == "EXECUTED"])


def applied_order_count(rule_id):
    return len([o for o in db.orders.values()
                if o.get("rule_id") == rule_id and o["status"] == "EXECUTED"])


def honored_claim_count(policy_id):
    return len([c for c in db.claims.values()
                if c["policy_id"] == policy_id and c["status"] == "HONORED"])


# ==================================================== per-product benchmark

def _benchmark_candidates(product):
    """PRD 3.5/3.6: the single shared benchmark selector."""
    survivors = []
    for link in db.links.values():
        if link["product_id"] != product["id"]:
            continue
        if link["status"] != "CONFIRMED":
            continue
        if link.get("data_status") != "SUFFICIENT":
            continue
        if link.get("confidence_bp") is None or link["confidence_bp"] < MIN_INDEX_CONFIDENCE_BP:
            continue
        competitor = db.competitors.get(link["competitor_id"])
        if competitor is None or competitor["status"] != "ACTIVE":
            continue
        if competitor["tier"] != "PRIMARY":
            continue
        survivors.append(link)
    survivors.sort(key=lambda l: (l["latest_effective_price_cents"],
                                  l["created_at"], l["_seq"]))
    return survivors


def benchmark_price(product):
    survivors = _benchmark_candidates(product)
    if not survivors:
        return None
    return survivors[0]["latest_effective_price_cents"]


def select_benchmark_or_fail(product):
    price = benchmark_price(product)
    if price is None:
        raise err("ERR_NO_COMPETITOR_BENCHMARK",
                  "No qualifying CONFIRMED match provides a competitor benchmark.")
    return price


# ============================================================== price index

def basket_candidates(market_id, category_code):
    rows = []
    for product in db.ordered(db.products):
        if product["market_id"] != market_id:
            continue
        if product["status"] != "ACTIVE":
            continue
        if category_code != "*" and product["category_code"] != category_code:
            continue
        rows.append(product)
    return rows


def price_index(market, category_code, basis):
    """PRD 3.5. Returns the computed report fields as a dict."""
    candidates = basket_candidates(market["id"], category_code)
    candidate_product_count = len(candidates)

    matched = []      # (product, ratio_bp)
    unmatched = []
    for product in candidates:
        bench = benchmark_price(product)
        if bench is None:
            unmatched.append(product)
        else:
            ratio_bp = round_half_up(product["own_price_cents"] * 10000, bench)
            matched.append((product, ratio_bp))
    matched_product_count = len(matched)

    if matched_product_count == 0:
        index_bp = None
        data_sufficiency = "INSUFFICIENT"
        imputed_product_count = 0
        excluded_product_count = candidate_product_count
    else:
        data_sufficiency = "SUFFICIENT"
        if basis == "MATCHED_BASKET":
            basket = list(matched)
            imputed_product_count = 0
        else:
            ordered_ratios = sorted(matched,
                                    key=lambda pair: (pair[1],
                                                      pair[0]["created_at"],
                                                      pair[0]["_seq"]))
            imputed_ratio_bp = median_half_up([ratio for _, ratio in ordered_ratios])
            basket = list(matched) + [(p, imputed_ratio_bp) for p in unmatched]
            imputed_product_count = candidate_product_count - matched_product_count
        weight_sum = sum(p["index_weight_bp"] for p, _ in basket)
        weighted = sum(ratio * p["index_weight_bp"] for p, ratio in basket)
        index_bp = round_half_up(weighted, weight_sum)
        excluded_product_count = (candidate_product_count - matched_product_count
                                  - imputed_product_count)

    if index_bp is None:
        positioning_gap_bp = None
        positioning_verdict = "INDETERMINATE"
    else:
        positioning_gap_bp = index_bp - market["strategic_index_target_bp"]
        if abs(positioning_gap_bp) <= market["index_tolerance_bp"]:
            positioning_verdict = "ON_TARGET"
        elif positioning_gap_bp > 0:
            positioning_verdict = "ABOVE_TARGET"
        else:
            positioning_verdict = "BELOW_TARGET"

    return {
        "index_bp": index_bp,
        "candidate_product_count": candidate_product_count,
        "matched_product_count": matched_product_count,
        "imputed_product_count": imputed_product_count,
        "excluded_product_count": excluded_product_count,
        "data_sufficiency": data_sufficiency,
        "positioning_gap_bp": positioning_gap_bp,
        "positioning_verdict": positioning_verdict,
    }


def perception_validation(perception_survey_index_bp, index_bp):
    """PRD 3.5: inclusive at exactly 200 basis points."""
    if perception_survey_index_bp is None or index_bp is None:
        return "INDETERMINATE"
    if abs(perception_survey_index_bp - index_bp) <= PERCEPTION_AGREEMENT_BP:
        return "CONFIRMS"
    return "CONTRADICTS"


# ==================================================== market posture (PRD 3.5)

def market_posture_fields(market):
    governing = [r for r in db.reports.values()
                 if r["market_id"] == market["id"] and r["status"] == "PUBLISHED"]
    governing.sort(key=lambda r: (-r["published_at"].timestamp(),
                                  r["created_at"], r["_seq"]))
    if not governing:
        observed_index_bp = None
        positioning_gap_bp = None
    else:
        observed_index_bp = governing[0]["index_bp"]
        if observed_index_bp is None:
            positioning_gap_bp = None
        else:
            positioning_gap_bp = observed_index_bp - market["strategic_index_target_bp"]

    insufficient_data_report_count = len(
        [r for r in db.reports.values()
         if r["market_id"] == market["id"]
         and r["data_sufficiency"] == "INSUFFICIENT"
         and r["status"] in ("DRAFT", "PUBLISHED")])

    drift = 0 if positioning_gap_bp is None else abs(positioning_gap_bp)
    tolerance = market["index_tolerance_bp"]
    if drift > POSTURE_FROZEN_MULTIPLIER * tolerance:
        posture = "FROZEN"
    elif drift > POSTURE_RESTRICTED_MULTIPLIER * tolerance or insufficient_data_report_count >= 1:
        posture = "RESTRICTED"
    else:
        posture = "OPEN"

    return {
        "observed_index_bp": observed_index_bp,
        "positioning_gap_bp": positioning_gap_bp,
        "insufficient_data_report_count": insufficient_data_report_count,
        "pricing_posture": posture,
    }


# ================================================= repricing rule selection

def select_rule_or_fail(product):
    """PRD 3.6: priority DESC, specificity DESC, created_at ASC."""
    candidates = []
    for rule in db.rules.values():
        if rule["market_id"] != product["market_id"]:
            continue
        if rule["status"] != "ACTIVE":
            continue
        if rule["category_code"] != "*" and rule["category_code"] != product["category_code"]:
            continue
        if product["brand"] in rule["brand_exclusions"]:
            continue
        candidates.append(rule)
    if not candidates:
        raise err("ERR_NO_APPLICABLE_REPRICING_RULE",
                  "No ACTIVE repricing rule applies to this product.")
    candidates.sort(key=lambda r: (-r["priority"],
                                   0 if r["category_code"] == "*" else -1,
                                   r["created_at"], r["_seq"]))
    return candidates[0]


# ====================================================== repricing proposal

def repricing_proposal(product, origin, rule=None, benchmark_price_cents=None,
                       hand_set_price_cents=None):
    """PRD 3.6: target -> band clamp -> floor clamp, in that pinned order."""
    from util import dec
    floor_cents = effective_floor_cents(product)
    own_price = product["own_price_cents"]

    if origin == "AUTOMATED_RULE":
        target_price_cents = round_half_up(
            benchmark_price_cents * rule["target_position_bp"], 10000)
        max_step_cents = floor_div(dec(own_price) * dec(rule["max_change_pct"]))
        band_low = own_price - max_step_cents
        band_high = own_price + max_step_cents
        banded_price_cents = min(max(target_price_cents, band_low), band_high)
    else:
        target_price_cents = hand_set_price_cents
        band_low = 0
        band_high = None
        banded_price_cents = max(target_price_cents, band_low)

    proposed_price_cents = max(banded_price_cents, floor_cents)
    floor_binding = banded_price_cents < floor_cents
    band_breach = (proposed_price_cents < band_low
                   or (band_high is not None and proposed_price_cents > band_high))

    return {
        "target_price_cents": target_price_cents,
        "banded_price_cents": banded_price_cents,
        "effective_floor_cents": floor_cents,
        "proposed_price_cents": proposed_price_cents,
        "floor_binding": bool(floor_binding),
        "band_breach": bool(band_breach),
    }


# ================================================ price match honored price

def price_match_honored_price(claimed_price_cents, product, store):
    """PRD 3.8: the beat-bonus tier is keyed on the claimed price only."""
    from util import dec
    if claimed_price_cents < BEAT_BONUS_TIER1_MAX_CENTS:
        tier_pct = dec("0.00")
    elif claimed_price_cents < BEAT_BONUS_TIER2_MAX_CENTS:
        tier_pct = dec("0.05")
    else:
        tier_pct = dec("0.10")

    beat_bonus_cents = min(round_half_up(dec(claimed_price_cents) * tier_pct),
                           BEAT_BONUS_CAP_CENTS)
    pre_floor_cents = claimed_price_cents - beat_bonus_cents
    floor_cents = effective_floor_cents(product)
    honored_price_cents = max(pre_floor_cents, floor_cents)
    discount_cents = product["own_price_cents"] - honored_price_cents
    required_approval_tier = ("ASSOCIATE"
                              if discount_cents <= store["override_authority_cents"]
                              else "MANAGER")
    return {
        "beat_bonus_cents": beat_bonus_cents,
        "honored_price_cents": honored_price_cents,
        "discount_cents": discount_cents,
        "required_approval_tier": required_approval_tier,
    }


def confirmed_link_for_pair(product_id, competitor_id):
    matches = [l for l in db.ordered(db.links)
               if l["product_id"] == product_id
               and l["competitor_id"] == competitor_id
               and l["status"] == "CONFIRMED"]
    return matches[0] if matches else None


def frequency_limit_satisfied(product, rule):
    """PRD 3.7: whole days between last_price_change_at and the logical clock."""
    if rule is None:
        return True
    last = product.get("last_price_change_at")
    if last is None:
        return True
    return whole_days_between(last, clock.now()) >= rule["change_frequency_limit_days"]
