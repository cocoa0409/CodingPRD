"""The nine declared calculations, as pure functions."""
from decimal import Decimal

from common import D, cents, q1, q2, q3, tenths

LBS_PER_TON = 2000
BRIX_ROT_TENTHS_SCALE = 10

MAX_OFFER_ROUNDS = 3
MAX_PICK_CALL_REVISIONS = 2
DELIVERY_GRACE_HOURS = 72
LATE_ARRIVAL_GRACE_MINUTES = 60
GRADE_DISPUTE_WINDOW_HOURS = 72
RENEWAL_MIN_RELIABILITY_SCORE = Decimal("80.0")

PROMPT_TIER_1_CENTS = 5000000
PROMPT_TIER_2_CENTS = 10000000
PROMPT_TIER_3_CENTS = 15000000

REJECTED_LOAD_UNITS = 8
EXPIRED_CALL_UNITS = 5
NO_SHOW_UNITS = 3
RELIABILITY_BASE = 100
PRIOR_VINTAGE_DECAY_DIVISOR = 2

ZERO = Decimal("0")
ZERO3 = Decimal("0.000")


# --------------------------------------------------------------------------
# 1. net_weight_conversion
# --------------------------------------------------------------------------
def net_weight_conversion(gross_weight_lbs, tare_weight_lbs):
    net_weight_lbs = int(gross_weight_lbs) - int(tare_weight_lbs)
    net_tons = q3(D(net_weight_lbs) / D(LBS_PER_TON))
    return net_weight_lbs, net_tons


# --------------------------------------------------------------------------
# 2. quality_adjustment_pct
# --------------------------------------------------------------------------
def quality_adjustment_pct(spec, brix, ta_gl, rot_pct, mog_pct):
    t_brix = tenths(brix)
    t_bonus_start = tenths(spec["brix_bonus_start"])
    t_penalty_start = tenths(spec["brix_penalty_start"])
    t_step = tenths(spec["brix_step"])

    if t_brix > t_bonus_start:
        bonus_steps = (t_brix - t_bonus_start) // t_step if t_step else 0
        brix_component = q1(D(bonus_steps) * D(spec["brix_bonus_pct_per_step"]))
    elif t_brix < t_penalty_start:
        penalty_steps = (t_penalty_start - t_brix) // t_step if t_step else 0
        brix_component = q1(-D(penalty_steps) * D(spec["brix_penalty_pct_per_step"]))
    else:
        brix_component = q1(ZERO)

    t_ta = tenths(ta_gl)
    if t_ta < tenths(spec["ta_min_gl"]) or t_ta > tenths(spec["ta_max_gl"]):
        acid_component = q1(-D(spec["acid_out_of_spec_penalty_pct"]))
    else:
        acid_component = q1(ZERO)

    t_rot = tenths(rot_pct)
    t_rot_free = tenths(spec["rot_free_pct"])
    if t_rot > t_rot_free:
        whole_points = (t_rot - t_rot_free) // BRIX_ROT_TENTHS_SCALE
        rot_component = q1(-D(whole_points) * D(spec["rot_penalty_pct_per_point"]))
    else:
        rot_component = q1(ZERO)

    if tenths(mog_pct) > tenths(spec["mog_max_pct"]):
        mog_component = q1(-D(spec["mog_penalty_pct"]))
    else:
        mog_component = q1(ZERO)

    raw = q1(brix_component + acid_component + rot_component + mog_component)
    adjustment = clamp_adjustment(spec, raw)

    if t_brix < tenths(spec["min_brix_accept"]) or t_rot >= tenths(spec["rot_rejection_pct"]):
        recommended = "REJECT_QUALITY"
    else:
        recommended = "ACCEPT"

    return {
        "brix_component_pct": brix_component,
        "acid_component_pct": acid_component,
        "rot_component_pct": rot_component,
        "mog_component_pct": mog_component,
        "raw_adjustment_pct": raw,
        "adjustment_pct": adjustment,
        "recommended_disposition": recommended,
    }


def clamp_adjustment(spec, raw):
    """The single clamp: min(max_bonus, max(-max_penalty, raw))."""
    ceiling = D(spec["max_total_bonus_pct"])
    floor = -D(spec["max_total_penalty_pct"])
    value = raw
    if value > ceiling:
        value = ceiling
    if value < floor:
        value = floor
    return q1(value)


# --------------------------------------------------------------------------
# 4. tonnage_waterfall_allocation
# --------------------------------------------------------------------------
def tonnage_waterfall(net_tons, soft_cap, hard_cap, consumed_soft, consumed_total,
                      over_delivery_policy):
    soft_remaining = q3(max(ZERO3, q3(D(soft_cap) - D(consumed_soft))))
    hard_remaining = q3(max(ZERO3, q3(D(hard_cap) - D(consumed_total))))

    net_tons = q3(net_tons)
    contract_slice = q3(min(net_tons, soft_remaining))
    remainder = q3(net_tons - contract_slice)

    band_capacity = q3(max(ZERO3, q3(hard_remaining - contract_slice)))
    band_slice = q3(min(remainder, band_capacity))

    if over_delivery_policy == "REJECT":
        over_slice = ZERO3
        over_rejected = band_slice
    else:
        over_slice = band_slice
        over_rejected = ZERO3

    excess_rejected = q3(remainder - band_slice)

    if contract_slice + over_slice == ZERO3:
        disposition = "REJECTED_OVER_CAP"
    elif over_rejected > ZERO3 or excess_rejected > ZERO3:
        disposition = "PARTIALLY_ACCEPTED"
    else:
        disposition = "ACCEPTED"

    return {
        "contract_slice_tons": q3(contract_slice),
        "over_slice_tons": q3(over_slice),
        "over_rejected_tons": q3(over_rejected),
        "excess_rejected_tons": q3(excess_rejected),
        "disposition": disposition,
    }


# --------------------------------------------------------------------------
# 5. settlement_line_amount
# --------------------------------------------------------------------------
def settlement_line_amount(contract, bucket, tons, adjustment_pct):
    if bucket == "CONTRACT":
        applied = q1(D(adjustment_pct))
        base_cents = int(contract["base_price_per_ton_cents"])
    else:
        applied = q1(min(D(adjustment_pct), Decimal("0.0")))
        if contract["over_delivery_policy"] == "ACCEPT_AT_SPOT":
            base_cents = cents(D(contract["base_price_per_ton_cents"])
                               * D(contract["spot_price_pct"]) / D(100))
        else:
            base_cents = int(contract["base_price_per_ton_cents"])

    # step 2 -- INNER rounding
    price_per_ton_cents = cents(D(base_cents) * (Decimal(1) + applied / D(100)))
    # step 3 -- OUTER rounding
    gross_amount_cents = cents(D(price_per_ton_cents) * q3(tons))
    # step 4 -- provisional advance
    provisional_amount_cents = cents(D(gross_amount_cents)
                                     * D(contract["provisional_payment_pct"]) / D(100))

    return {
        "adjustment_pct_applied": applied,
        "price_per_ton_cents": price_per_ton_cents,
        "gross_amount_cents": gross_amount_cents,
        "provisional_amount_cents": provisional_amount_cents,
    }


# --------------------------------------------------------------------------
# 7. net_payable_derivation
# --------------------------------------------------------------------------
def prompt_pay_rate_pct(settlement_total_cents):
    total = int(settlement_total_cents)
    if total < PROMPT_TIER_1_CENTS:
        return Decimal("0.0")
    if total < PROMPT_TIER_2_CENTS:
        return Decimal("0.5")
    if total < PROMPT_TIER_3_CENTS:
        return Decimal("1.0")
    return Decimal("1.5")


def net_payable_derivation(settlement_total_cents, lien_holdback_pct):
    total = int(settlement_total_cents)
    rate_pct = prompt_pay_rate_pct(total)
    prompt_pay_credit_cents = cents(D(total) * rate_pct / D(100))
    lien_holdback_cents = cents(D(total) * D(lien_holdback_pct) / D(100))
    net_payable_cents = total + prompt_pay_credit_cents - lien_holdback_cents
    return {
        "final_settlement_cents": total,
        "prompt_pay_credit_cents": prompt_pay_credit_cents,
        "lien_holdback_cents": lien_holdback_cents,
        "net_payable_cents": net_payable_cents,
    }


# --------------------------------------------------------------------------
# 9. grower_reliability_score
# --------------------------------------------------------------------------
def penalty_units(rejected, expired, no_shows):
    return (REJECTED_LOAD_UNITS * int(rejected)
            + EXPIRED_CALL_UNITS * int(expired)
            + NO_SHOW_UNITS * int(no_shows))


def reliability_vintage(current_units):
    return q1(max(Decimal("0.0"), D(RELIABILITY_BASE) - D(current_units)))


def reliability_lifetime(current_units, prior_units):
    halved = cents(D(prior_units) / D(PRIOR_VINTAGE_DECAY_DIVISOR))
    return q1(max(Decimal("0.0"),
                  D(RELIABILITY_BASE) - D(current_units) - D(halved)))


# --------------------------------------------------------------------------
# 3. tonnage_cap_derivation helper
# --------------------------------------------------------------------------
def inflate(cap_tons, tolerance_pct):
    return q3(D(cap_tons) * (Decimal(1) + D(tolerance_pct) / D(100)))


def clamp_raw(spec, value):
    """Clamp without re-quantising -- used by the WEIGHTED_BLEND 2-decimal blend."""
    ceiling = D(spec["max_total_bonus_pct"])
    floor = -D(spec["max_total_penalty_pct"])
    if value > ceiling:
        return ceiling
    if value < floor:
        return floor
    return value
