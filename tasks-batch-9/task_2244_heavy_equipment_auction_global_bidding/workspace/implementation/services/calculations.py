"""The seven normative calculations (PRD sections 3.3, 3.6, 3.7, 3.8, 3.9)."""
from decimal import Decimal

from db import db
from services import constants as C
from services.money import cents, dec, pct, round_half_up


# ==========================================================================
# 1. lot_condition_grade
# ==========================================================================
def condition_grade(scores, hour_meter_verified):
    """`scores` maps STRUCTURAL/POWERTRAIN/HYDRAULICS/TIRES to Decimal values.

    Each weighted component is rounded to two decimals *first*, then the four
    rounded components are summed — the rounding step is normative.
    """
    components = [
        round_half_up(dec(scores["structural"]) * C.GRADE_WEIGHT_STRUCTURAL, 2),
        round_half_up(dec(scores["powertrain"]) * C.GRADE_WEIGHT_POWERTRAIN, 2),
        round_half_up(dec(scores["hydraulics"]) * C.GRADE_WEIGHT_HYDRAULICS, 2),
        round_half_up(dec(scores["tires"]) * C.GRADE_WEIGHT_TIRES, 2),
    ]
    raw = sum(components, Decimal("0"))
    if hour_meter_verified:
        grade_score = raw
    else:
        grade_score = raw - C.UNVERIFIED_HOUR_METER_PENALTY
        if grade_score < 0:
            grade_score = Decimal("0")
    grade_score = round_half_up(grade_score, 2)

    if grade_score >= C.GRADE_BAND_A_MIN:
        band = "A"
    elif grade_score >= C.GRADE_BAND_B_MIN:
        band = "B"
    elif grade_score >= C.GRADE_BAND_C_MIN:
        band = "C"
    else:
        band = "D"
    if not hour_meter_verified and band in ("A", "B"):
        band = "C"
    return grade_score, band


def hour_meter_variance_pct(observed, declared):
    denominator = max(declared or 0, 1)
    return round_half_up(abs(dec(observed) - dec(declared)) / dec(denominator), 4)


# ==========================================================================
# 2. buyer_premium_computation
# ==========================================================================
def sale_sort_key(sale):
    return (sale["hammered_at"], sale["created_at"], sale["_seq"])


def prior_hammer_total(sale):
    """Sum of hammer prices already knocked down to the same registration in
    the same auction, strictly earlier in (hammered_at, created_at) order."""
    key = sale_sort_key(sale)
    total = 0
    for other in db.sales.values():
        if other["id"] == sale["id"]:
            continue
        if other["auction_id"] != sale["auction_id"]:
            continue
        if other["registration_id"] != sale["registration_id"]:
            continue
        if other["status"] not in ("CONFIRMED", "SETTLED"):
            continue
        if sale_sort_key(other) < key:
            total += other["hammer_price_cents"] or 0
    return total


def buyer_premium(hammer_price_cents, auction, prior_total=0):
    if auction["premium_schedule_code"] == "LOW_VALUE_FLAT":
        flat = pct(hammer_price_cents, C.LOW_VALUE_FLAT_RATE)
        return max(C.LOW_VALUE_FLAT_MIN_CENTS, flat)

    hammer = hammer_price_cents
    tier1 = pct(min(hammer, C.PREMIUM_TIER1_CEILING_CENTS), C.PREMIUM_TIER1_RATE)
    tier2 = pct(
        max(0, min(hammer, C.PREMIUM_TIER2_CEILING_CENTS) - C.PREMIUM_TIER1_CEILING_CENTS),
        C.PREMIUM_TIER2_RATE,
    )
    tier3 = pct(max(0, hammer - C.PREMIUM_TIER2_CEILING_CENTS), C.PREMIUM_TIER3_RATE)
    premium = tier1 + tier2 + tier3

    if auction["kind"] == "TIMED_ONLINE":
        premium += pct(hammer, C.ONLINE_SURCHARGE_RATE)

    if prior_total >= C.VOLUME_TIER2_THRESHOLD_CENTS:
        discount_pct = C.VOLUME_TIER2_DISCOUNT
    elif prior_total >= C.VOLUME_TIER1_THRESHOLD_CENTS:
        discount_pct = C.VOLUME_TIER1_DISCOUNT
    else:
        discount_pct = Decimal("0")
    if discount_pct > 0:
        premium = premium - pct(premium, discount_pct)

    return min(C.PREMIUM_MAX_CENTS, max(C.PREMIUM_MIN_CENTS, premium))


# ==========================================================================
# 3. storage_fee_accrual
# ==========================================================================
def payment_terms_for(registration):
    terms = registration.get("payment_terms_code")
    return terms if terms in C.DUE_DAYS_BY_TERMS else "PREPAY"


def derive_payment_terms(financing_approved, country_tier):
    if financing_approved:
        return "NET_30"
    if country_tier == "TIER_A":
        return "NET_7"
    return "PREPAY"


def storage_daily_rate(weight_kg):
    if weight_kg <= C.STORAGE_LIGHT_MAX_KG:
        return C.STORAGE_RATE_LIGHT_CENTS
    if weight_kg <= C.STORAGE_MEDIUM_MAX_KG:
        return C.STORAGE_RATE_MEDIUM_CENTS
    return C.STORAGE_RATE_HEAVY_CENTS


def storage_accrual(grace_end_at, now, weight_kg, hammer_price_cents):
    elapsed = (now - grace_end_at).total_seconds()
    if elapsed < 0:
        elapsed = 0
    chargeable_days = int(elapsed // 86400)
    uncapped = chargeable_days * storage_daily_rate(weight_kg)
    cap = pct(hammer_price_cents, C.STORAGE_CAP_RATE)
    return chargeable_days, min(uncapped, cap)


# ==========================================================================
# 4. bidder_exposure_and_bid_cap
# ==========================================================================
def country_tier(country_code):
    if country_code in C.COUNTRY_TIER_A_CODES:
        return "TIER_A"
    if country_code in C.COUNTRY_TIER_B_CODES:
        return "TIER_B"
    return "TIER_C"


def base_headroom(registration):
    leverage = registration.get("leverage_multiplier") or 0
    return (registration["deposit_hold_cents"] or 0) * leverage


def forecast_exposure(registration):
    total = 0
    for invoice in db.invoices.values():
        if invoice["registration_id"] != registration["id"]:
            continue
        if invoice["payment_status"] not in ("UNPAID", "PARTIALLY_PAID"):
            continue
        sale = db.sales.get(invoice["sale_id"])
        if not sale or sale["status"] not in ("CONFIRMED", "SETTLED"):
            continue
        total += invoice["total_due_cents"] or 0
    return total


def registration_forecast_cap(registration):
    exposure = forecast_exposure(registration)
    cap = base_headroom(registration) + (
        registration.get("approved_credit_limit_cents") or 0) - exposure
    return max(0, cap), exposure


def live_chronological_cap(registration):
    """Replay the registration's knock-downs in hammered_at order."""
    headroom = base_headroom(registration)
    consumed = 0
    breached_at_sale_id = None
    sales = [s for s in db.sales.values()
             if s["registration_id"] == registration["id"] and s["status"] != "NO_SALE"]
    for sale in sorted(sales, key=sale_sort_key):
        headroom -= sale["hammer_price_cents"] or 0
        consumed += sale["hammer_price_cents"] or 0
        if headroom <= 0 and breached_at_sale_id is None:
            breached_at_sale_id = sale["id"]
    return max(0, headroom), consumed, breached_at_sale_id


# ==========================================================================
# 5. consignor_net_proceeds
# ==========================================================================
def commission_for(schedule_code, gross_cents):
    schedule = C.COMMISSION_SCHEDULES[schedule_code]
    tier1 = pct(min(gross_cents, schedule["tier1_ceiling"]), schedule["tier1_rate"])
    tier2 = pct(max(0, gross_cents - schedule["tier1_ceiling"]), schedule["tier2_rate"])
    return max(schedule["floor"], tier1 + tier2)


# ==========================================================================
# 6. abandonment_deficiency
# ==========================================================================
def deficiency_claim(hammer_price_cents, storage_fee_cents, deposit_hold_cents,
                     amount_paid_cents):
    return max(
        0,
        hammer_price_cents + storage_fee_cents + C.ABANDONMENT_ADMIN_FEE_CENTS
        - deposit_hold_cents - amount_paid_cents,
    )
