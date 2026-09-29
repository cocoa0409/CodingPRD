"""All eleven calculation rules (PRD 3 / scaffold 1.3).

Every monetary and rate computation goes through decimal.Decimal with
ROUND_HALF_UP; no float arithmetic anywhere in this module.
"""

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP, getcontext

import clock
import db as store
from db import db, ordered, touch

getcontext().prec = 60

ZERO = Decimal(0)

# --- panelist_fraud_risk_score constants -------------------------------------
W_ADDR = Decimal(18)
W_AGE = Decimal(22)
W_STRIKE = Decimal(25)
W_REFERRAL = Decimal(15)
W_VELOCITY = Decimal(20)
W_RESALE = Decimal(30)
ACCOUNT_AGE_FLOOR_DAYS = 30
VELOCITY_TRIP_COUNT = 3
AUDIT_ADDR_MULTIPLIER = Decimal("1.5")
FLAG_THRESHOLD_INCLUSIVE = Decimal("55.0")
VELOCITY_WINDOW_DAYS = 7

# --- panelist_cooldown_overlap ----------------------------------------------
PANELIST_COOLDOWN_DAYS = 14

# --- campaign_compliance_posture --------------------------------------------
FROZEN_RATE = Decimal("0.2")
FROZEN_ABS = 5
RESTRICTED_RATE = Decimal("0.05")
RESTRICTED_DISCLOSURE_ABS = 3

# --- review_disclosure_gate -------------------------------------------------
REQUIRED_DISCLOSURE_PHRASES = ("i received this product for free", "sample provided by")

# --- syndication_eligibility ------------------------------------------------
BADGE_PHRASE = "i received this product for free"
RATE_LIMIT_WINDOW_DAYS = 30

# --- campaign_lift_and_diversion_penalty ------------------------------------
MATCH_CONFIDENCE_FLOOR = Decimal("0.8")
CONVERSION_TAIL_DAYS = 30
MIN_TREATED_FOR_POWER = 3
PENALTY_TIER_LOW = 500
PENALTY_TIER_HIGH = 1500


def rhu(value, places=0):
    """ROUND_HALF_UP to `places` decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


# ============================================================ kit assembly cost

def extended_cost_cents(kit_line):
    """ROUND_HALF_UP(unit_cost_cents * quantity_per_kit * (1 - discount), 0)."""
    unit = Decimal(kit_line["unit_cost_cents"])
    qty = Decimal(kit_line["quantity_per_kit"])
    discount = kit_line["component_discount_pct"]
    if not isinstance(discount, Decimal):
        discount = Decimal(str(discount))
    return rhu_int(unit * qty * (Decimal(1) - discount))


def active_kit_lines(campaign_id):
    """ACTIVE lines of a campaign, ordered created_at ASC then component_sku ASC."""
    rows = [k for k in db.kit_lines.values()
            if k["campaign_id"] == campaign_id and k["status"] == "ACTIVE"]
    return sorted(rows, key=lambda k: (k["created_at"], k["component_sku"]))


def kit_assembly_unit_cost_cents(campaign_id):
    """Sum of the already-rounded per-line extended costs (round-per-line, then sum)."""
    total = 0
    for line in active_kit_lines(campaign_id):
        total += line["extended_cost_cents"]
    return total


def refresh_kit_assembly_unit_cost(campaign):
    campaign["kit_assembly_unit_cost_cents"] = kit_assembly_unit_cost_cents(campaign["id"])


# ================================================================ cost per sample

PROVISIONAL_STATUSES = ("ALLOCATED", "SHIPPED", "DELIVERED", "LOST")
FINAL_NUMERATOR_STATUSES = ("DELIVERED", "LOST")


def cost_per_sample_provisional_cents(campaign):
    population = [s for s in store.campaign_shipments(campaign["id"])
                  if s["status"] in PROVISIONAL_STATUSES]
    if not population:
        return 0
    kit_cost = Decimal(campaign["kit_assembly_unit_cost_cents"])
    numerator = ZERO
    for shipment in population:
        numerator += kit_cost + Decimal(store.freight_of_shipment(shipment))
    return rhu_int(numerator / Decimal(len(population)))


def cost_per_sample_final_cents(campaign):
    shipments = store.campaign_shipments(campaign["id"])
    numerator_population = [s for s in shipments if s["status"] in FINAL_NUMERATOR_STATUSES]
    delivered = [s for s in shipments if s["status"] == "DELIVERED"]
    if not delivered:
        return 0
    kit_cost = Decimal(campaign["kit_assembly_unit_cost_cents"])
    numerator = ZERO
    for shipment in numerator_population:
        numerator += (kit_cost
                      + Decimal(store.freight_of_shipment(shipment))
                      + Decimal(shipment["surcharge_cents"]))
    numerator += Decimal(campaign["write_off_cost_cents"])
    return rhu_int(numerator / Decimal(len(delivered)))


def refresh_provisional_cost(campaign):
    campaign["cost_per_sample_provisional_cents"] = cost_per_sample_provisional_cents(campaign)


def refresh_final_cost(campaign):
    campaign["cost_per_sample_final_cents"] = cost_per_sample_final_cents(campaign)


# ========================================================= panelist fraud score

def _address_collisions(panelist):
    count = 0
    for other in db.panelists.values():
        if other["id"] == panelist["id"]:
            continue
        if other["address_hash"] == panelist["address_hash"]:
            count += 1
    return count


def _address_base(panelist):
    collisions = _address_collisions(panelist)
    return W_ADDR * Decimal(min(3, collisions)) / Decimal(3)


def _age_term(panelist):
    opened = clock.sec(clock.parse(panelist["account_opened_at"]))
    now = clock.sec(clock.now())
    delta_days = (now - opened).total_seconds() // 86400
    age_days = int(delta_days)
    return W_AGE if age_days < ACCOUNT_AGE_FLOOR_DAYS else ZERO


def _strike_term(panelist):
    strikes = Decimal(panelist["diversion_strikes"])
    return min(W_STRIKE, W_STRIKE * strikes / Decimal(2))


def _referral_term(panelist):
    referrer_id = panelist.get("referred_by_panelist_id")
    if not referrer_id:
        return ZERO
    referrer = db.panelists.get(referrer_id)
    if referrer is None:
        return ZERO
    if referrer["integrity_status"] in ("FLAGGED", "BANNED"):
        return W_REFERRAL
    return ZERO


def _velocity_term(panelist):
    now = clock.sec(clock.now())
    window_from = now - clock.days(VELOCITY_WINDOW_DAYS)
    count = 0
    for enrollment in store.panelist_enrollments(panelist["id"]):
        for review in store.enrollment_reviews(enrollment["id"]):
            if review["status"] not in ("SUBMITTED", "APPROVED", "RETRACTED"):
                continue
            if not review.get("first_submitted_at"):
                continue
            stamp = clock.sec(clock.parse(review["first_submitted_at"]))
            if window_from <= stamp <= now:
                count += 1
    return W_VELOCITY if count >= VELOCITY_TRIP_COUNT else ZERO


def _resale_term(panelist):
    open_cases = 0
    for case in store.panelist_diversion_cases(panelist["id"]):
        if case["status"] in ("INVESTIGATING", "SUBSTANTIATED"):
            open_cases += 1
    return W_RESALE * Decimal(min(2, open_cases)) / Decimal(2)


def fraud_risk_score(panelist, variant):
    """variant is SCREENING or AUDIT; result is capped at 100.0, 1 decimal place."""
    addr_base = _address_base(panelist)
    age = _age_term(panelist)
    strike = _strike_term(panelist)
    referral = _referral_term(panelist)
    if variant == "SCREENING":
        raw = addr_base + age + strike + referral
    else:
        raw = (AUDIT_ADDR_MULTIPLIER * addr_base + age + strike + referral
               + _velocity_term(panelist) + _resale_term(panelist))
    raw = min(Decimal(100), max(ZERO, raw))
    return rhu(raw, 1)


def rescore_panelist(panelist, variant):
    """Writes the score, stamps last_risk_scored_at, bumps version by 1.

    Applies the AUDIT flagging rule (score >= 55.0 and CLEAR -> FLAGGED).
    """
    score = fraud_risk_score(panelist, variant)
    if variant == "SCREENING":
        panelist["fraud_risk_score_screening"] = score
    else:
        panelist["fraud_risk_score_audit"] = score
        if score >= FLAG_THRESHOLD_INCLUSIVE and panelist["integrity_status"] == "CLEAR":
            panelist["integrity_status"] = "FLAGGED"
    panelist["last_risk_scored_at"] = clock.now_iso()
    touch(panelist)
    return score


# ============================================================ cooldown overlap

def cooldown_conflict(enrollment):
    """True when the candidate campaign window collides with an occupied window."""
    candidate_campaign = store.campaign_of_enrollment(enrollment)
    cand_from = clock.sec(clock.parse(candidate_campaign["sampling_window_start"]))
    cand_to = clock.sec(clock.parse(candidate_campaign["sampling_window_end"]))
    for prior in store.panelist_enrollments(enrollment["panelist_id"]):
        if prior["id"] == enrollment["id"]:
            continue
        if prior["screening_status"] != "SCREEN_PASSED":
            continue
        prior_campaign = store.campaign_of_enrollment(prior)
        if prior_campaign is None:
            continue
        occupied_from = clock.sec(clock.parse(prior_campaign["sampling_window_start"]))
        occupied_to = (clock.sec(clock.parse(prior_campaign["sampling_window_end"]))
                       + clock.days(PANELIST_COOLDOWN_DAYS))
        if cand_from <= occupied_to and cand_to >= occupied_from:
            return True
    return False


# ======================================================== eligibility screening

def eligibility_screening_decision(enrollment, panelist, campaign):
    """Returns (True, None) on pass, (False, reason) on failure."""
    if panelist["integrity_status"] != "CLEAR":
        return False, "INTEGRITY_HOLD"
    if panelist["segment_code"] not in campaign["target_segment_codes"]:
        return False, "SEGMENT_MISMATCH"
    if panelist["fraud_risk_score_screening"] >= FLAG_THRESHOLD_INCLUSIVE:
        return False, "FRAUD_SCORE_TOO_HIGH"
    if cooldown_conflict(enrollment):
        return False, "COOLDOWN_CONFLICT"
    return True, None


# =========================================================== holdout assignment

def holdout_flag_for(campaign, enrollment_seq):
    pct = campaign["holdout_pct"]
    if not isinstance(pct, Decimal):
        pct = Decimal(str(pct))
    n = Decimal(enrollment_seq)
    current = (n * pct).to_integral_value(rounding=ROUND_FLOOR)
    previous = ((n - 1) * pct).to_integral_value(rounding=ROUND_FLOOR)
    return current > previous


# ============================================================= wave capacity

def wave_capacity_error(wave, units):
    """Returns an error_id or None.  Per-wave ceiling first, then the center."""
    if wave["planned_unit_count"] + units > wave["planned_capacity_units"]:
        return "ERR_WAVE_CAPACITY_EXCEEDED"
    center = store.center_of_wave(wave)
    wave_start = clock.sec(clock.parse(wave["window_start"]))
    wave_end = clock.sec(clock.parse(wave["window_end"]))
    occupied = 0
    for other in ordered(db.fulfillment_waves.values()):
        if other["fulfillment_center_id"] != center["id"]:
            continue
        if other["status"] not in ("PLANNED", "LOCKED"):
            continue
        other_start = clock.sec(clock.parse(other["window_start"]))
        other_end = clock.sec(clock.parse(other["window_end"]))
        if other_start < wave_end and other_end > wave_start:
            occupied += other["planned_unit_count"]
    if occupied + units > center["daily_pick_capacity_units"]:
        return "ERR_CENTER_CAPACITY_EXCEEDED"
    return None


# ========================================================= kit reservation

def kit_unit_total_for(campaign_id):
    return sum(line["quantity_per_kit"] for line in active_kit_lines(campaign_id))


def kit_reservation(campaign_id):
    """Returns (reserved_line_units, kit_unit_total) or raises the stock error id."""
    lines = active_kit_lines(campaign_id)
    if not lines:
        return None, "ERR_CAMPAIGN_KIT_EMPTY"
    for line in lines:
        if line["units_available"] < line["quantity_per_kit"]:
            return None, "ERR_KIT_STOCK_INSUFFICIENT"
    reserved = {}
    total = 0
    for line in lines:
        reserved[line["id"]] = line["quantity_per_kit"]
        total += line["quantity_per_kit"]
    return (reserved, total), None


# ======================================================= compliance posture

def compliance_posture(campaign):
    delivered = campaign["delivered_sample_count"]
    substantiated = campaign["substantiated_diversion_count"]
    if delivered == 0:
        rate = ZERO
    else:
        rate = rhu(Decimal(substantiated) / Decimal(delivered), 4)
    if rate >= FROZEN_RATE or substantiated >= FROZEN_ABS:
        return "FROZEN"
    if (rate >= RESTRICTED_RATE
            or campaign["disclosure_rejected_review_count"] >= RESTRICTED_DISCLOSURE_ABS):
        return "RESTRICTED"
    return "OPEN"


def refresh_posture(campaign):
    campaign["compliance_posture"] = compliance_posture(campaign)


# ========================================================= review disclosure

def word_count(text):
    if not isinstance(text, str):
        return 0
    return len([token for token in text.split() if token])


def disclosure_present(disclosure_statement):
    if not isinstance(disclosure_statement, str) or disclosure_statement.strip() == "":
        return False
    lowered = disclosure_statement.lower()
    return any(phrase in lowered for phrase in REQUIRED_DISCLOSURE_PHRASES)


# ====================================================== syndication eligibility

def syndication_decision(review, retailer, panelist):
    """Returns (True, None) or (False, rejection_reason)."""
    if review["star_rating"] < retailer["min_star_rating_accepted"]:
        return False, "BELOW_MIN_RATING"
    if retailer["requires_disclosure_badge"]:
        statement = review.get("disclosure_statement")
        lowered = statement.lower() if isinstance(statement, str) else ""
        if BADGE_PHRASE not in lowered:
            return False, "DISCLOSURE_BADGE_MISSING"
    now = clock.sec(clock.now())
    window_from = now - clock.days(RATE_LIMIT_WINDOW_DAYS)
    recent = 0
    for record in ordered(db.syndication_records.values()):
        if record["retailer_id"] != retailer["id"]:
            continue
        if record["status"] != "SYNDICATED":
            continue
        other_review = store.review_of_syndication(record)
        if other_review is None:
            continue
        other_panelist = store.panelist_of_review(other_review)
        if other_panelist is None or other_panelist["id"] != panelist["id"]:
            continue
        stamp = record.get("syndicated_at")
        if not stamp:
            continue
        stamp = clock.sec(clock.parse(stamp))
        if window_from <= stamp <= now:
            recent += 1
    if recent >= retailer["max_reviews_per_panelist_per_month"]:
        return False, "PANELIST_RATE_LIMIT"
    return True, None


# =========================================== lift analysis + diversion penalty

def _qualified_conversion(enrollment, campaign):
    window_from = clock.sec(clock.parse(campaign["sampling_window_start"]))
    window_to = (clock.sec(clock.parse(campaign["sampling_window_end"]))
                 + clock.days(CONVERSION_TAIL_DAYS))
    for match in ordered(db.purchase_matches.values()):
        if match["enrollment_id"] != enrollment["id"]:
            continue
        if match["match_confidence"] < MATCH_CONFIDENCE_FLOOR:
            continue
        purchased_at = clock.sec(clock.parse(match["purchased_at"]))
        if window_from <= purchased_at <= window_to:
            return True
    return False


def _has_delivered_shipment(enrollment):
    for shipment in store.enrollment_shipments(enrollment["id"]):
        if shipment["status"] == "DELIVERED":
            return True
    return False


def compute_lift(campaign, variant):
    enrollments = store.campaign_enrollments(campaign["id"])
    holdout_group = [e for e in enrollments
                     if e["holdout_flag"] and e["screening_status"] == "SCREEN_PASSED"]
    treated_group = [e for e in enrollments
                     if not e["holdout_flag"] and e["screening_status"] == "SCREEN_PASSED"]
    if variant == "PER_PROTOCOL":
        treated_group = [e for e in treated_group if _has_delivered_shipment(e)]

    treated_count = len(treated_group)
    holdout_count = len(holdout_group)
    treated_converted = sum(1 for e in treated_group if _qualified_conversion(e, campaign))
    holdout_converted = sum(1 for e in holdout_group if _qualified_conversion(e, campaign))

    treated_rate = (ZERO if treated_count == 0
                    else rhu(Decimal(treated_converted) / Decimal(treated_count), 4))
    holdout_rate = (ZERO if holdout_count == 0
                    else rhu(Decimal(holdout_converted) / Decimal(holdout_count), 4))
    lift_pct = rhu(Decimal(100) * (treated_rate - holdout_rate), 2)
    if holdout_count == 0 or treated_count < MIN_TREATED_FOR_POWER:
        power_status = "INSUFFICIENT_POWER"
    else:
        power_status = "MEASURED"

    # ---- diversion penalty, four pinned steps
    diverted = campaign["substantiated_diversion_count"]
    effective = campaign["delivered_sample_count"] - diverted
    committed = Decimal(campaign["budget_committed_cents"])
    if effective <= 0:
        base = 0
    else:
        base = rhu_int(committed / Decimal(effective))
    if base < PENALTY_TIER_LOW:
        penalty_rate_pct = 10
    elif base < PENALTY_TIER_HIGH:
        penalty_rate_pct = 20
    else:
        penalty_rate_pct = 35
    penalty = rhu_int(Decimal(base) * Decimal(penalty_rate_pct) / Decimal(100)
                      * Decimal(diverted))
    if effective <= 0:
        adjusted = 0
    else:
        adjusted = rhu_int((committed + Decimal(penalty)) / Decimal(effective))

    return {
        "treated_count": treated_count,
        "holdout_count": holdout_count,
        "treated_converted_count": treated_converted,
        "holdout_converted_count": holdout_converted,
        "treated_conversion_rate": rhu(treated_rate, 4),
        "holdout_conversion_rate": rhu(holdout_rate, 4),
        "lift_pct": lift_pct,
        "power_status": power_status,
        "effective_sample_count": effective,
        "diverted_unit_count": diverted,
        "base_cost_per_sample_cents": base,
        "penalty_rate_pct": penalty_rate_pct,
        "diversion_penalty_cents": penalty,
        "adjusted_cost_per_sample_cents": adjusted,
    }
