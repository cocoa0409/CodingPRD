"""All arithmetic rules (PRD 2.6 and section 3).

Every monetary field is an integer number of cents; every rate is a Decimal.
Rounding is ROUND HALF UP everywhere, and rounding happens before any
tolerance comparison.
"""

from decimal import Decimal, ROUND_HALF_UP

import db

# ------------------------------------------------------------------ constants
SAMPLE_THRESHOLD_QTY = 40
SAMPLE_RATE_NUM = 10
SAMPLE_RATE_DEN = 100

TIER_MULTIPLIER = {
    "PREFERRED": Decimal("1.15"),
    "STANDARD": Decimal("1.00"),
    "PROBATION": Decimal("0.80"),
}
TIERED_FEE_CENTS = ((99, 8), (499, 7), (None, 6))

HOLDBACK_BAND_1_CENTS = 100000
HOLDBACK_BAND_2_CENTS = 1000000
HOLDBACK_RISK_ADD_PCT = Decimal("0.03")
HOLDBACK_CAP_PCT = Decimal("0.06")
MISREDEMPTION_RISK_THRESHOLD_PCT = Decimal("5.00")

DUP_WEIGHT = Decimal("1.40")
MIS_WEIGHT = Decimal("1.00")
CFT_WEIGHT = Decimal("2.00")
FRAUD_WINDOW_DAYS = 90
FRAUD_DECAY_HALFLIFE_DAYS = 180
FRAUD_WATCHLIST_THRESHOLD = Decimal("70.00")
FRAUD_SUSPEND_THRESHOLD = Decimal("90.00")
FRAUD_SCORE_CAP = Decimal("100.00")

CLEARING_FEE_PCT = Decimal("0.015")
NET_TERM_DAYS = {"NET_15": 15, "NET_30": 30, "NET_45": 45}

CLIP_CONCURRENCY_LIMIT = 2
COUNT_VARIANCE_TOLERANCE_PCT = Decimal("2.00")
MAX_INFO_ROUNDS = 2
DISPUTE_SLA_DAYS = 30
BILLING_PERIOD_BUFFER_DAYS = 1

DATABAR_FAMILY_CODE = "811"
UPC_COUPON_NUMBER_SYSTEM = "5"
EXT5_UNITS_MULTIPLIER = 1000

REJECTED_STATUSES = (
    "REJECTED_COUNTERFEIT",
    "REJECTED_EXPIRED",
    "REJECTED_DUPLICATE",
    "REJECTED_MISREDEEMED",
)
CLEARED_STATUSES = ("ACCEPTED", "REINSTATED")
SETTLEABLE_LOT_STATUSES = ("VALIDATED", "REINSTATED")

ZERO_2 = Decimal("0.00")
ZERO_4 = Decimal("0.0000")


def rhu(value, places):
    """Round half up to `places` decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def ceil_div(numerator, denominator):
    return -((-numerator) // denominator)


# ------------------------------------------------------------------ barcodes
def barcode_payload(offer, manufacturer):
    """PRD 3.2 barcode minting."""
    prefix = manufacturer["gs1_company_prefix"]
    face5 = "%05d" % offer["face_value_cents"]
    units2 = "%02d" % offer["purchase_requirement_units"]
    grace3 = "%03d" % offer["redemption_grace_days"]
    expiry = db.parse_date(offer["expiration_date"])
    yymmdd = "%02d%02d%02d" % (expiry.year % 100, expiry.month, expiry.day)
    if offer["barcode_family"] == "GS1_DATABAR":
        return DATABAR_FAMILY_CODE + prefix + face5 + units2 + yymmdd + grace3
    ext5 = "%05d" % (
        offer["purchase_requirement_units"] * EXT5_UNITS_MULTIPLIER
        + offer["redemption_grace_days"]
    )
    return UPC_COUPON_NUMBER_SYSTEM + prefix + face5 + ext5


# ------------------------------------------------------------------ sampling
def sample_plan(counted_qty):
    """Returns (sample_size, valuation_variant)."""
    if counted_qty <= SAMPLE_THRESHOLD_QTY:
        return counted_qty, "FULL_COUNT"
    return (
        ceil_div(counted_qty * SAMPLE_RATE_NUM, SAMPLE_RATE_DEN),
        "SAMPLED_EXTRAPOLATION",
    )


def count_variance_pct(verified_count, declared_count):
    return rhu(
        Decimal(abs(verified_count - declared_count)) * Decimal(100)
        / Decimal(declared_count),
        2,
    )


# ------------------------------------------------------------------ valuation
def lot_valuation(variant, accepted_qty, counted_qty, sample_size, face_value_cents):
    """Returns (projected_accepted_units, gross_face_value_cents)."""
    if variant == "FULL_COUNT":
        projected = accepted_qty
    else:
        if not sample_size:
            return 0, 0
        rate = rhu(Decimal(accepted_qty) / Decimal(sample_size), 4)
        projected = rhu_int(Decimal(counted_qty) * rate)
    return projected, projected * face_value_cents


def extrapolated_rate(accepted_qty, sample_size):
    if not sample_size:
        return ZERO_4
    return rhu(Decimal(accepted_qty) / Decimal(sample_size), 4)


def per_unit_fee_cents(offer, manufacturer, units):
    if manufacturer["handling_fee_policy"] == "CONTRACT_RATE":
        return offer["handling_fee_cents"]
    for ceiling, cents in TIERED_FEE_CENTS:
        if ceiling is None or units <= ceiling:
            return cents
    return TIERED_FEE_CENTS[-1][1]


def handling_fee_cents(units, offer, manufacturer, retailer):
    """PRD 3.5 handling fee, rounded once at the lot level."""
    per_unit = per_unit_fee_cents(offer, manufacturer, units)
    multiplier = TIER_MULTIPLIER.get(retailer["handling_fee_tier"], Decimal("1.00"))
    return rhu_int(Decimal(units) * Decimal(per_unit) * multiplier)


# ------------------------------------------------------------------ settlement
def holdback_pct(provisional_net_cents, retailer):
    if provisional_net_cents < HOLDBACK_BAND_1_CENTS:
        base = Decimal("0.00")
    elif provisional_net_cents < HOLDBACK_BAND_2_CENTS:
        base = Decimal("0.02")
    else:
        base = Decimal("0.05")
    add_on = (
        HOLDBACK_RISK_ADD_PCT
        if retailer["misredemption_rate"] >= MISREDEMPTION_RISK_THRESHOLD_PCT
        else Decimal("0.00")
    )
    return rhu(min(base + add_on, HOLDBACK_CAP_PCT), 4)


def clearing_fee_cents(billed_face_value_cents):
    return rhu_int(Decimal(billed_face_value_cents) * CLEARING_FEE_PCT)


def scheduled_pay_date(clock_date, payment_terms):
    target = db.add_days(clock_date, NET_TERM_DAYS[payment_terms])
    weekday = target.weekday()  # Monday == 0
    if weekday == 5:            # Saturday
        target = db.add_days(target, 2)
    elif weekday == 6:          # Sunday
        target = db.add_days(target, 1)
    return target
