"""Calculation rules (SCAFFOLD 1.3 / PRD 2.8, 3.2, 3.3, 3.4, 3.6, 3.7, 3.8).

All monetary arithmetic is exact decimal arithmetic on integer cents; rates are
applied with round-half-up and caps are floored, per PRD 2.8.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

DAY = timedelta(seconds=86400)

# --- required_storage_category --------------------------------------------
HIGH_VALUE_THRESHOLD_CENTS = 500000

# --- retention_release_at -------------------------------------------------
ADJUDICATED_RETENTION_FACTOR = Decimal("0.5")
MIN_RETENTION_DAYS = 90

# --- disposition_proceeds -------------------------------------------------
ESTIMATE_COMMISSION_RATE = Decimal("0.10")
COMMISSION_TIER_LOW_MAX_CENTS = 50000
COMMISSION_TIER_LOW_RATE = Decimal("0.15")
COMMISSION_TIER_MID_MAX_CENTS = 500000
COMMISSION_TIER_MID_RATE = Decimal("0.10")
COMMISSION_TIER_HIGH_RATE = Decimal("0.07")
STORAGE_RECOVERY_CAP_PCT = Decimal("0.30")
STORAGE_RATE_CENTS_PER_DAY = {
    "GENERAL": 25,
    "REFRIGERATED": 120,
    "HIGH_VALUE_VAULT": 60,
    "OVERSIZED_YARD": 200,
}
SETTLEMENT_WINDOW_DAYS = 30

# --- audit_risk_index -----------------------------------------------------
KIND_WEIGHT_MISSING = Decimal("5.0")
KIND_WEIGHT_MISPLACED = Decimal("2.0")
VALUE_DIVISOR_CENTS = Decimal("1000000")
VALUE_MULTIPLIER_CAP = Decimal("2.0")
SENSITIVE_CATEGORY_MULTIPLIER = Decimal("1.5")
SENSITIVE_LOCATION_CATEGORIES = ("HIGH_VALUE_VAULT", "REFRIGERATED")

# --- room_posture ---------------------------------------------------------
HIGH_RISK_MISSING_LIMIT = 1
OPEN_DISCREPANCY_LOCKDOWN_LIMIT = 5
RISK_INDEX_LOCKDOWN_THRESHOLD = Decimal("25.00")

# --- owner_claim_deadline -------------------------------------------------
FOUND_PROPERTY_NOTICE_DAYS = 90
SEIZED_PROPERTY_NOTICE_DAYS = 30
PUBLICATION_EXTRA_DAYS = 15

# --- escorts / windows ----------------------------------------------------
MAX_CONCURRENT_ESCORTS = 2
MAX_WINDOW_DAYS_BY_PURPOSE = {
    "LAB_ANALYSIS": 30,
    "COURT_PRESENTATION": 3,
    "INVESTIGATIVE_REVIEW": 7,
}
AUDIT_BUFFER_HOURS = 48

HIGH_RISK_CATEGORIES = ("FIREARM", "CURRENCY", "NARCOTICS")

# a refrigerated bin running warmer than this is ineligible to receive items
REFRIGERATION_MAX_OK_C = Decimal("4.0")

PACKAGING_BY_CATEGORY = {
    "BIOLOGICAL": ("SHARPS_TUBE", "RIGID_BOX"),
    "CURRENCY": ("SEALED_ENVELOPE",),
    "FIREARM": ("RIGID_BOX", "CHAIN_TAG_ONLY"),
    "NARCOTICS": ("SEALED_ENVELOPE", "RIGID_BOX"),
    "OVERSIZED": ("PALLET_WRAP", "CHAIN_TAG_ONLY"),
    "GENERAL": ("SEALED_ENVELOPE", "PAPER_BAG", "RIGID_BOX", "PALLET_WRAP", "CHAIN_TAG_ONLY"),
}


def rhu_cents(value):
    """Round half up to whole cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(value):
    """Round half up to two decimal places."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def add_days(instant, days):
    return instant + DAY * days


def add_seconds(instant, seconds):
    return instant + timedelta(seconds=seconds)


# --------------------------------------------------------------------------
# required_storage_category
# --------------------------------------------------------------------------

def required_storage_category(category, appraised_value_cents):
    if category == "BIOLOGICAL":
        return "REFRIGERATED"
    if category in ("CURRENCY", "FIREARM", "NARCOTICS"):
        return "HIGH_VALUE_VAULT"
    if category == "OVERSIZED":
        return "OVERSIZED_YARD"
    if appraised_value_cents >= HIGH_VALUE_THRESHOLD_CENTS:
        return "HIGH_VALUE_VAULT"
    return "GENERAL"


def packaging_permitted(category, packaging_type):
    return packaging_type in PACKAGING_BY_CATEGORY.get(category, ())


# --------------------------------------------------------------------------
# barcode_assignment
# --------------------------------------------------------------------------

def barcode(agency_code, case_number, item_sequence):
    padded = "%04d" % item_sequence
    body = "%s%s%s" % (agency_code, case_number, padded)
    digits = [int(ch) for ch in body if ch.isdigit()]
    weighted = 0
    for index, digit in enumerate(reversed(digits)):
        weighted += digit * (3 if index % 2 == 0 else 1)
    check_digit = (10 - (weighted % 10)) % 10
    return "%s-%s-%s-%d" % (agency_code, case_number, padded, check_digit)


# --------------------------------------------------------------------------
# retention_release_at
# --------------------------------------------------------------------------

def retention(item, case, statute, requested_basis):
    """Returns (resolved_basis, anchor_at, statute_days_applied, release_at)."""
    if item["disposition_state"] == "COURT_HOLD" or case["status"] == "APPEAL_PENDING":
        return "COURT_HOLD", None, 0, None
    if statute["preservation_class"] in ("BIOLOGICAL_INDEFINITE", "HOMICIDE_PERMANENT"):
        return "INDEFINITE", None, 0, None
    if requested_basis == "PRELIMINARY":
        anchor = item["intake_at"]
        days = statute["statutory_retention_days"]
        return "PRELIMINARY", anchor, days, add_days(anchor, days)
    anchor = case["adjudicated_at"]
    half = statute["statutory_retention_days"] * ADJUDICATED_RETENTION_FACTOR
    half_days = int(half.to_integral_value(rounding="ROUND_CEILING"))
    days = statute["appeal_window_days"] + half_days
    candidate = add_days(anchor, days)
    floor_at = add_days(item["intake_at"], MIN_RETENTION_DAYS)
    return "FINAL", anchor, days, max(candidate, floor_at)


# --------------------------------------------------------------------------
# disposition_proceeds
# --------------------------------------------------------------------------

def estimated_net_proceeds(order_type, appraised_value_cents):
    if order_type != "AUCTION":
        return 0
    commission = rhu_cents(Decimal(appraised_value_cents) * ESTIMATE_COMMISSION_RATE)
    return appraised_value_cents - commission


def commission_rate(gross_sale_cents):
    if gross_sale_cents <= COMMISSION_TIER_LOW_MAX_CENTS:
        return COMMISSION_TIER_LOW_RATE
    if gross_sale_cents <= COMMISSION_TIER_MID_MAX_CENTS:
        return COMMISSION_TIER_MID_RATE
    return COMMISSION_TIER_HIGH_RATE


def storage_days(intake_at, executed_at):
    seconds = (executed_at - intake_at).total_seconds()
    return int(seconds // 86400)


def settled_proceeds(gross_sale_cents, intake_at, executed_at, required_category):
    """The five pinned steps of the SETTLED variant."""
    rate = commission_rate(gross_sale_cents)
    commission = rhu_cents(Decimal(gross_sale_cents) * rate)          # step 1
    subtotal = gross_sale_cents - commission                          # step 2
    cap = int((Decimal(subtotal) * STORAGE_RECOVERY_CAP_PCT).to_integral_value(
        rounding="ROUND_FLOOR"))                                      # step 3
    days = storage_days(intake_at, executed_at)
    raw_recovery = days * STORAGE_RATE_CENTS_PER_DAY[required_category]
    recovery = min(raw_recovery, cap)                                 # step 4
    net = subtotal - recovery                                         # step 5
    return commission, recovery, net


# --------------------------------------------------------------------------
# audit_risk_index
# --------------------------------------------------------------------------

def weight_contribution(kind, appraised_value_cents, location_category):
    kind_weight = KIND_WEIGHT_MISSING if kind == "MISSING" else KIND_WEIGHT_MISPLACED
    value_multiplier = Decimal(1) + min(
        Decimal(appraised_value_cents) / VALUE_DIVISOR_CENTS, VALUE_MULTIPLIER_CAP
    )
    category_multiplier = (
        SENSITIVE_CATEGORY_MULTIPLIER
        if location_category in SENSITIVE_LOCATION_CATEGORIES
        else Decimal("1.0")
    )
    return rhu2(kind_weight * value_multiplier * category_multiplier)


# --------------------------------------------------------------------------
# owner_claim_deadline
# --------------------------------------------------------------------------

def owner_claim_deadline(notified_at, is_found_property, notice_method):
    base_days = FOUND_PROPERTY_NOTICE_DAYS if is_found_property else SEIZED_PROPERTY_NOTICE_DAYS
    extra_days = PUBLICATION_EXTRA_DAYS if notice_method == "PUBLICATION" else 0
    return add_days(notified_at, base_days + extra_days)


# --------------------------------------------------------------------------
# auto_authorization_predicate
# --------------------------------------------------------------------------

def auto_authorized(order_type, statute, item):
    return (
        order_type == "DESTRUCTION"
        and statute["destruction_requires_court_order"] is False
        and item["category"] not in ("FIREARM", "CURRENCY", "NARCOTICS", "BIOLOGICAL")
        and item["appraised_value_cents"] < HIGH_VALUE_THRESHOLD_CENTS
    )
