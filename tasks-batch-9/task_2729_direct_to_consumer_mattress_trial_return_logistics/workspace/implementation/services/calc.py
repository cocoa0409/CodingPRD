"""Named constants and the declared calculations, in whole cents / basis points.

All arithmetic is exact integer arithmetic; rhu() is round half up with ties
away from zero and is applied only where the specification names a rounding.
"""
from util import rhu, whole_days, whole_years

# ---------------------------------------------------------------- pricing ---
BPS_DIVISOR = 10000

# --------------------------------------------------------- refund settlement --
USAGE_RETENTION_BPS = 2500
TIER1_MAX_NIGHTS = 30
TIER1_BPS = 0
TIER2_MAX_NIGHTS = 60
TIER2_BPS = 500
TIER3_MAX_NIGHTS = 100
TIER3_BPS = 1200
TIER4_BPS = 2000

# ------------------------------------------------------------ damage offset --
GRADE_OFFSET_BPS = {"A": 0, "B": 500, "C": 1500, "D": 3000}
SOIL_OFFSET_BPS = 1000
DAMAGE_OFFSET_CAP_BPS = 4000
CONDITION_GRADES = ("A", "B", "C", "D")

# -------------------------------------------------------------- abuse score --
SIGNAL_WEIGHTS = {
    "REPEAT_RETURN": 25,
    "HOUSEHOLD_MATCH": 30,
    "SHORT_TRIAL": 15,
    "MULTI_CHANNEL": 10,
}
SIGNAL_TYPES = tuple(SIGNAL_WEIGHTS.keys())
DECAY_STEP_DAYS = 180
WINDOW_DAYS = 365
SCORE_CEILING = 100
ABUSE_RESTRICT_THRESHOLD = 60
ABUSE_BLOCK_THRESHOLD = 80
ABUSE_BLOCK_DAYS = 365
SHORT_TRIAL_NIGHTS = 30

# ------------------------------------------------------ exchange settlement --
EXCHANGE_FEE_BASE_CENTS = 9900
EXCHANGE_FEE_STEP_CENTS = 5000
EXCHANGE_FEE_CAP_CENTS = 24900
TIER_A_MAX_CENTS = 20000
TIER_A_CREDIT_BPS = 0
TIER_B_MAX_CENTS = 50000
TIER_B_CREDIT_BPS = 250
TIER_C_CREDIT_BPS = 500
MAX_EXCHANGES_PER_CHAIN = 2

# ------------------------------------------------------------ pickup units ---
SIZE_UNITS = {"TWIN": 1, "QUEEN": 2, "KING": 3}

# ------------------------------------------------------------ quality claim --
MIN_PHOTOS_DELIVERY = 2
MIN_PHOTOS_STRAIGHTEDGE = 3
MIN_PHOTOS_LASER = 1
DAMAGE_GOODWILL_BPS = 1500
COMPRESSION_GOODWILL_CENTS = 7500
WARRANTY_DECAY_BPS_PER_YEAR = 1000
WARRANTY_FLOOR_BPS = 2000
MAX_EVIDENCE_ROUNDS = 2
COMPRESSION_RECOVERY_WAIT_NIGHTS = 3
DAMAGE_REPORT_WINDOW_NIGHTS = 7

# -------------------------------------------------------------- attribution --
MIN_CLAIM_EVIDENCE = 2
PRICE_MATCH_CAP_BPS = 1000
MAX_REVISION_ROUNDS = 2

# ---------------------------------------------------------------- household --
HOUSEHOLD_TRIAL_LIMIT = 2


def order_pricing(gross_price_cents, percent_off_bps):
    """bundle_discount_cents then paid_amount_cents; a single rounding."""
    discount = rhu(gross_price_cents * percent_off_bps, BPS_DIVISOR)
    return discount, gross_price_cents - discount


def proration_provisional(gross_refundable_cents, nights_used, trial_nights):
    """gross * min(n, T) * USAGE_RETENTION_BPS / (T * 10000), one rounding."""
    used = min(nights_used, trial_nights)
    return rhu(gross_refundable_cents * used * USAGE_RETENTION_BPS,
               trial_nights * BPS_DIVISOR)


def final_tier_bps(nights_used):
    if nights_used <= TIER1_MAX_NIGHTS:
        return TIER1_BPS
    if nights_used <= TIER2_MAX_NIGHTS:
        return TIER2_BPS
    if nights_used <= TIER3_MAX_NIGHTS:
        return TIER3_BPS
    return TIER4_BPS


def proration_final(gross_refundable_cents, nights_used):
    """A flat tier applied to the whole gross, not a marginal band."""
    return rhu(gross_refundable_cents * final_tier_bps(nights_used),
               BPS_DIVISOR)


def bundle_unwind(bundle, gross_price_cents, bundle_discount_cents,
                  nights_used, trial_nights, accessory_returned):
    """Three components, each rounded to whole cents before they are summed."""
    if bundle is None:
        return 0
    waived = bool(bundle["requires_accessory_return"]) and bool(
        accessory_returned)
    policy = bundle["unwind_policy"]
    accessory = bundle["accessory_retail_cents"]
    gift = bundle["gift_card_cents"]
    unearned = trial_nights - min(nights_used, trial_nights)

    if policy == "FORFEIT_NONE" or waived:
        accessory_component = 0
    elif policy == "DEDUCT_RETAIL":
        accessory_component = accessory
    else:
        accessory_component = rhu(accessory * unearned, trial_nights)

    if policy == "FORFEIT_NONE" or waived or accessory == 0:
        discount_component = 0
    else:
        discount_component = rhu(bundle_discount_cents * accessory,
                                 accessory + gross_price_cents)

    if policy == "FORFEIT_NONE":
        gift_component = 0
    elif policy == "DEDUCT_RETAIL":
        gift_component = gift
    else:
        gift_component = rhu(gift * unearned, trial_nights)

    return accessory_component + discount_component + gift_component


def damage_offset(paid_amount_cents, condition_grade, soil_flag):
    grade_bps = GRADE_OFFSET_BPS[condition_grade]
    soil_bps = SOIL_OFFSET_BPS if soil_flag else 0
    effective = min(grade_bps + soil_bps, DAMAGE_OFFSET_CAP_BPS)
    return rhu(paid_amount_cents * effective, BPS_DIVISOR)


def signal_weight(signal_type):
    return SIGNAL_WEIGHTS[signal_type]


def abuse_scores(signals, clock):
    """Rolling score decays in two steps by signal age; the lifetime score never
    decays. Each total is summed first and capped once at SCORE_CEILING."""
    rolling = 0
    lifetime = 0
    for signal in signals:
        weight = signal["weight"]
        age_days = whole_days(signal["recorded_at"], clock)
        if age_days is None:
            age_days = 0
        if age_days < DECAY_STEP_DAYS:
            rolling += weight
        elif age_days < WINDOW_DAYS:
            rolling += rhu(weight, 2)
        lifetime += weight
    return min(rolling, SCORE_CEILING), min(lifetime, SCORE_CEILING)


def exchange_fee(sequence_number):
    return min(EXCHANGE_FEE_CAP_CENTS,
               EXCHANGE_FEE_BASE_CENTS
               + (sequence_number - 1) * EXCHANGE_FEE_STEP_CENTS)


def tier_credit_bps(raw_price_difference_cents):
    """The tier is keyed on the absolute RAW difference, before fee or credit."""
    magnitude = abs(raw_price_difference_cents)
    if magnitude < TIER_A_MAX_CENTS:
        return TIER_A_CREDIT_BPS
    if magnitude < TIER_B_MAX_CENTS:
        return TIER_B_CREDIT_BPS
    return TIER_C_CREDIT_BPS


def exchange_settlement(original_order, original_model, target_model):
    raw = target_model["list_price_cents"] - original_model["list_price_cents"]
    sequence_number = original_order["exchange_chain_depth"] + 1
    fee = exchange_fee(sequence_number)
    credit = rhu(original_order["paid_amount_cents"] * tier_credit_bps(raw),
                 BPS_DIVISOR)
    difference = raw + fee - credit
    if difference > 0:
        direction = "CHARGE_CUSTOMER"
    elif difference < 0:
        direction = "CREDIT_CUSTOMER"
    else:
        direction = "EVEN"
    return {
        "sequence_number": sequence_number,
        "raw_price_difference_cents": raw,
        "exchange_fee_cents": fee,
        "tier_credit_cents": credit,
        "price_difference_cents": difference,
        "settlement_direction": direction,
    }


def units_for_size(size):
    return SIZE_UNITS[size]


def required_photos(claim_type, measurement_method):
    if claim_type == "WARRANTY_INDENTATION":
        if measurement_method == "LASER_SCAN":
            return MIN_PHOTOS_LASER
        return MIN_PHOTOS_STRAIGHTEDGE
    return MIN_PHOTOS_DELIVERY


def warranty_coverage(delivered_at, reported_at):
    years = whole_years(delivered_at, reported_at)
    coverage = max(WARRANTY_FLOOR_BPS,
                   BPS_DIVISOR - years * WARRANTY_DECAY_BPS_PER_YEAR)
    return years, coverage


def quality_claim_credit(claim, paid_amount_cents):
    claim_type = claim["claim_type"]
    if claim_type == "SHIPPING_DAMAGE":
        return rhu(paid_amount_cents * DAMAGE_GOODWILL_BPS, BPS_DIVISOR)
    if claim_type == "COMPRESSION_RECOVERY":
        return COMPRESSION_GOODWILL_CENTS
    coverage = claim["coverage_bps"] or 0
    return rhu(paid_amount_cents * coverage, BPS_DIVISOR)


def commission_amount(paid_amount_cents, commission_bps):
    return rhu(paid_amount_cents * commission_bps, BPS_DIVISOR)


def price_match_credit(policy, gross_price_cents, competitor_price_cents):
    raw_gap = max(0, gross_price_cents - competitor_price_cents)
    if policy == "MATCH_TO_LOWEST":
        return raw_gap
    cap = rhu(gross_price_cents * PRICE_MATCH_CAP_BPS, BPS_DIVISOR)
    return min(raw_gap, cap)
