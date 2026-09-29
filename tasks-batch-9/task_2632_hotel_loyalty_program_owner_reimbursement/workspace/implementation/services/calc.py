"""Every arithmetic rule in the programme (PRD sections 2.7 and 3).

Money is integer cents throughout.  Percentage products are rounded half up to
the cent unless the PRD names a different direction; point earning floors down,
peak surcharges round up.
"""

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# enumerations
# ---------------------------------------------------------------------------

MARKET_TIERS = ("URBAN", "RESORT", "SELECT")
HOTEL_STATUSES = ("ONBOARDING", "ACTIVE", "FEE_DELINQUENT", "TERMINATED")
RATE_CATEGORIES = ("TRANSIENT", "CORPORATE_NEGOTIATED", "GROUP",
                   "OPAQUE_WHOLESALE", "EMPLOYEE_COMP", "AWARD")
SEASONS = ("STANDARD", "PEAK")
TIERS = ("BASE", "SILVER", "GOLD", "PLATINUM")
BLACKOUT_SCOPES = ("ALL_REDEMPTIONS", "STANDARD_ONLY")
BLACKOUT_STATUSES = ("DRAFT", "ACTIVE", "REVOKED")
STAY_STATUSES = ("PENDING_POSTING", "POSTED_QUALIFYING", "POSTED_NON_QUALIFYING",
                 "DISPUTED", "ADJUSTED", "VOID")
BENEFIT_TYPES = ("UPGRADE", "BREAKFAST", "LATE_CHECKOUT")
DELIVERY_STATUSES = ("OBLIGATED", "DELIVERED", "DENIED", "ESCALATED",
                     "DENIED_FINAL", "WAIVED")
FULFILLMENT_STATUSES = ("HELD", "CONFIRMED", "STAYED", "NO_SHOW", "CANCELLED")
REIMBURSEMENT_STATUSES = ("NOT_DUE", "ACCRUED", "BATCHED", "PAID", "VOIDED")
BATCH_STATUSES = ("OPEN", "RELEASED", "APPROVED", "REJECTED", "PAID")
ENTRY_TYPES = ("EARN_BASE", "EARN_BONUS", "PURCHASE", "PARTNER_SALE",
               "REDEEM", "REVERSAL", "GOODWILL")
PURCHASE_CHANNELS = ("CO_BRAND_CARD", "DIRECT_PURCHASE", "PARTNER_SALE")
PURCHASE_STATUSES = ("PENDING", "SETTLED", "REFUNDED")
PARTNER_TYPES = ("CO_BRAND_ISSUER", "AIRLINE", "RETAIL")
FUND_STATUSES = ("HEALTHY", "WATCH", "IMPAIRED")
COMPLAINT_SUBJECTS = ("BENEFIT_DENIAL", "POINT_SHORTFALL", "BLACKOUT_DISPUTE")
COMPLAINT_STATUSES = ("OPEN", "UNDER_REVIEW", "INFO_REQUESTED", "RESOLVED_GOODWILL",
                      "RESOLVED_UPHELD", "ESCALATED", "CLOSED")
ADJUDICATION_OUTCOMES = ("DELIVERY_ORDERED", "DENIAL_UPHELD")

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

EARN_RATE_BY_CATEGORY = {
    "TRANSIENT": 10,
    "CORPORATE_NEGOTIATED": 8,
    "GROUP": 6,
    "OPAQUE_WHOLESALE": 0,
    "EMPLOYEE_COMP": 0,
    "AWARD": 0,
}
QUALIFYING_CATEGORIES = ("TRANSIENT", "CORPORATE_NEGOTIATED", "GROUP")
ELITE_CREDIT_CATEGORIES = ("TRANSIENT", "CORPORATE_NEGOTIATED")

ELITE_BONUS_MULTIPLIER = {
    "BASE": Decimal("0.00"),
    "SILVER": Decimal("0.20"),
    "GOLD": Decimal("0.50"),
    "PLATINUM": Decimal("0.75"),
}

TIER_NIGHTS_PLATINUM = 50
TIER_NIGHTS_GOLD = 30
TIER_NIGHTS_SILVER = 10

BENEFIT_ENTITLEMENT = {
    "BASE": (),
    "SILVER": ("UPGRADE",),
    "GOLD": ("UPGRADE", "BREAKFAST"),
    "PLATINUM": ("UPGRADE", "BREAKFAST", "LATE_CHECKOUT"),
}

UPGRADE_ADR_PCT = Decimal("0.15")
UPGRADE_RECOVERY_CAP_CENTS = 9000
BREAKFAST_RECOVERY_PER_NIGHT_CENTS = 1800
LATE_CHECKOUT_RECOVERY_CENTS = 1200
BENEFIT_DENIAL_LIMIT = 3

TIER_DISCOUNT_PCT = {
    "BASE": Decimal("0.00"),
    "SILVER": Decimal("0.00"),
    "GOLD": Decimal("0.05"),
    "PLATINUM": Decimal("0.10"),
}
TIER_DISCOUNT_CAP_PER_NIGHT = 3000
FREE_NIGHT_MIN_NIGHTS = 5
PEAK_SURCHARGE_PCT = {
    "URBAN": Decimal("0.25"),
    "RESORT": Decimal("0.35"),
    "SELECT": Decimal("0.15"),
}
MIN_POINTS_PER_CHARGEABLE_NIGHT = 6000

FEE_DELINQUENCY_THRESHOLD_CENTS = 250000
FEE_LEDGER_STATUSES = ("POSTED_QUALIFYING", "POSTED_NON_QUALIFYING",
                       "DISPUTED", "ADJUSTED")

BLACKOUT_BUFFER_DAYS = 7
BLACKOUT_ANNUAL_CAP_DAYS = 60

OCCUPANCY_FULL_ADR_THRESHOLD = Decimal("0.95")
OCCUPANCY_PARTIAL_THRESHOLD = Decimal("0.80")
REIMBURSEMENT_PARTIAL_PCT = Decimal("0.75")
REIMBURSEMENT_FLOOR_PCT = Decimal("0.50")
REIMBURSEMENT_MIN_PER_NIGHT_CENTS = 3000

DELINQUENCY_SURCHARGE_NEGATIVE_PCT = Decimal("0.05")
DELINQUENCY_SURCHARGE_SMALL_PCT = Decimal("0.02")
DELINQUENCY_SURCHARGE_LARGE_PCT = Decimal("0.01")
DELINQUENCY_SURCHARGE_BAND_CENTS = 500000

DIRECT_LIST_PRICE_PER_1000_CENTS = 1250
VOLUME_DISCOUNT_LARGE_THRESHOLD = 100000
VOLUME_DISCOUNT_LARGE_PCT = Decimal("0.12")
VOLUME_DISCOUNT_SMALL_THRESHOLD = 25000
VOLUME_DISCOUNT_SMALL_PCT = Decimal("0.05")
CO_BRAND_BONUS_PCT = Decimal("0.10")
MEMBER_ANNUAL_PURCHASE_CAP_POINTS = 200000
POINT_QUANTITY_STEP = 1000

LIABILITY_UNIT_COST_CENTS_PER_1000 = 600
DEFAULT_BREAKAGE_RATE_PCT = Decimal("0.20")
MAX_BREAKAGE_RATE_PCT = Decimal("0.35")
SOLVENCY_SENTINEL = Decimal("999.0000")
SOLVENCY_HEALTHY_THRESHOLD = Decimal("1.0000")
SOLVENCY_WATCH_THRESHOLD = Decimal("0.7500")

INFO_REQUEST_LIMIT = 2

# ---------------------------------------------------------------------------
# rounding primitives
# ---------------------------------------------------------------------------

ONE = Decimal("1")
Q4 = Decimal("0.0001")


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def half_up(value):
    """Round a Decimal to a whole cent, half away from zero."""
    return int(dec(value).quantize(ONE, rounding=ROUND_HALF_UP))


def floor_int(value):
    return int(dec(value).quantize(ONE, rounding=ROUND_FLOOR))


def ceil_int(value):
    return int(dec(value).quantize(ONE, rounding=ROUND_CEILING))


def q4(value):
    return dec(value).quantize(Q4, rounding=ROUND_HALF_UP)


def as_float(value):
    return float(dec(value))


# ---------------------------------------------------------------------------
# rate plan derivation
# ---------------------------------------------------------------------------

def rate_plan_derivation(rate_category):
    return {
        "base_earn_rate_per_dollar": EARN_RATE_BY_CATEGORY[rate_category],
        "is_qualifying": rate_category in QUALIFYING_CATEGORIES,
        "counts_toward_elite": rate_category in ELITE_CREDIT_CATEGORIES,
        "program_fee_eligible": rate_category in QUALIFYING_CATEGORIES,
    }


# ---------------------------------------------------------------------------
# stay earning
# ---------------------------------------------------------------------------

def stay_base_points(room_revenue_cents, rate_plan):
    if not rate_plan.get("is_qualifying"):
        return 0
    if room_revenue_cents <= 0:
        return 0
    rate = rate_plan.get("base_earn_rate_per_dollar") or 0
    if rate <= 0:
        return 0
    return (room_revenue_cents * rate) // 100


def elite_bonus_points(base_points, tier):
    multiplier = ELITE_BONUS_MULTIPLIER.get(tier, Decimal("0.00"))
    if base_points <= 0 or multiplier == 0:
        return 0, multiplier
    return floor_int(Decimal(base_points) * multiplier), multiplier


def program_fee_assessment(room_revenue_cents, rate_plan, hotel):
    if not rate_plan.get("program_fee_eligible"):
        return 0
    if not rate_plan.get("is_qualifying"):
        return 0
    if room_revenue_cents <= 0:
        return 0
    return half_up(Decimal(room_revenue_cents) * dec(hotel.get("program_fee_pct") or 0))


def tier_for_nights(nights):
    if nights >= TIER_NIGHTS_PLATINUM:
        return "PLATINUM"
    if nights >= TIER_NIGHTS_GOLD:
        return "GOLD"
    if nights >= TIER_NIGHTS_SILVER:
        return "SILVER"
    return "BASE"


def entitled_benefits(tier):
    return BENEFIT_ENTITLEMENT.get(tier, ())


def benefit_cost_recovery(benefit_type, hotel, stay):
    if benefit_type == "UPGRADE":
        adr = hotel.get("trailing_12m_adr_cents") or 0
        return min(half_up(Decimal(adr) * UPGRADE_ADR_PCT), UPGRADE_RECOVERY_CAP_CENTS)
    if benefit_type == "BREAKFAST":
        return BREAKFAST_RECOVERY_PER_NIGHT_CENTS * int(stay.get("nights") or 0)
    if benefit_type == "LATE_CHECKOUT":
        return LATE_CHECKOUT_RECOVERY_CENTS
    return 0


# ---------------------------------------------------------------------------
# award pricing
# ---------------------------------------------------------------------------

def tier_rank(tier):
    try:
        return TIERS.index(tier)
    except ValueError:
        return 0


def redemption_points_price(points_per_night, nights, season, tier, market_tier):
    """Pinned order: tier discount, then free-night, then peak surcharge, then
    the six-thousand-per-chargeable-night floor."""
    nightly = int(points_per_night)
    pct = TIER_DISCOUNT_PCT.get(tier, Decimal("0.00"))
    discount_per_night = min(floor_int(Decimal(nightly) * pct), TIER_DISCOUNT_CAP_PER_NIGHT)
    if season == "STANDARD" and nights >= FREE_NIGHT_MIN_NIGHTS:
        chargeable = nights - 1
    else:
        chargeable = nights
    gross = (nightly - discount_per_night) * chargeable
    if season == "PEAK":
        surcharge = ceil_int(Decimal(gross) * PEAK_SURCHARGE_PCT.get(market_tier, Decimal("0")))
    else:
        surcharge = 0
    floor_price = MIN_POINTS_PER_CHARGEABLE_NIGHT * chargeable
    return max(gross + surcharge, floor_price)


# ---------------------------------------------------------------------------
# owner reimbursement
# ---------------------------------------------------------------------------

def reimbursement_rate_per_night(occupancy_pct, adr_cents):
    occupancy = dec(occupancy_pct)
    adr = int(adr_cents or 0)
    if occupancy >= OCCUPANCY_FULL_ADR_THRESHOLD:
        return adr
    if occupancy >= OCCUPANCY_PARTIAL_THRESHOLD:
        return half_up(Decimal(adr) * REIMBURSEMENT_PARTIAL_PCT)
    return max(half_up(Decimal(adr) * REIMBURSEMENT_FLOOR_PCT),
               REIMBURSEMENT_MIN_PER_NIGHT_CENTS)


def owner_reimbursement(occupancy_pct, adr_cents, nights):
    return reimbursement_rate_per_night(occupancy_pct, adr_cents) * int(nights)


def batch_net_payable(gross_cents, fee_offset_base_cents):
    net_before_surcharge = gross_cents - fee_offset_base_cents
    if net_before_surcharge < 0:
        pct = DELINQUENCY_SURCHARGE_NEGATIVE_PCT
    elif net_before_surcharge < DELINQUENCY_SURCHARGE_BAND_CENTS:
        pct = DELINQUENCY_SURCHARGE_SMALL_PCT
    else:
        pct = DELINQUENCY_SURCHARGE_LARGE_PCT
    surcharge = half_up(Decimal(fee_offset_base_cents) * pct)
    total_offset = fee_offset_base_cents + surcharge
    return surcharge, total_offset, gross_cents - total_offset


# ---------------------------------------------------------------------------
# point purchases
# ---------------------------------------------------------------------------

def volume_discount_pct(points_quantity):
    if points_quantity >= VOLUME_DISCOUNT_LARGE_THRESHOLD:
        return VOLUME_DISCOUNT_LARGE_PCT
    if points_quantity >= VOLUME_DISCOUNT_SMALL_THRESHOLD:
        return VOLUME_DISCOUNT_SMALL_PCT
    return Decimal("0.00")


def point_purchase_pricing(points_quantity, channel, partner):
    discount = volume_discount_pct(points_quantity)
    if channel == "PARTNER_SALE" and partner is not None:
        list_price = int(partner.get("points_cost_per_1000_cents") or 0)
    else:
        list_price = DIRECT_LIST_PRICE_PER_1000_CENTS
    cash_due = half_up(
        (Decimal(points_quantity) / Decimal(1000)) * Decimal(list_price) * (ONE - discount)
    )
    if channel == "CO_BRAND_CARD":
        bonus = floor_int(Decimal(points_quantity) * CO_BRAND_BONUS_PCT)
    else:
        bonus = 0
    return discount, cash_due, bonus


# ---------------------------------------------------------------------------
# point liability
# ---------------------------------------------------------------------------

def point_liability(outstanding_points, breakage_rate_pct):
    return half_up(
        Decimal(outstanding_points) * Decimal(LIABILITY_UNIT_COST_CENTS_PER_1000)
        / Decimal(1000) * (ONE - dec(breakage_rate_pct))
    )


def solvency(cash_balance_cents, point_liability_cents):
    if point_liability_cents == 0:
        return SOLVENCY_SENTINEL
    return q4(Decimal(cash_balance_cents) / Decimal(point_liability_cents))


def fund_status(solvency_ratio):
    ratio = dec(solvency_ratio)
    if ratio >= SOLVENCY_HEALTHY_THRESHOLD:
        return "HEALTHY"
    if ratio >= SOLVENCY_WATCH_THRESHOLD:
        return "WATCH"
    return "IMPAIRED"
