"""Constants and the pure arithmetic of PRD section 2.6 / 2.7 / 3."""

from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal("0.00")
TWO_PLACES = Decimal("0.01")
ONE = Decimal("1")

HOME_STATE_CODE = "MN"

PRODUCT_CODES = [
    "GASOLINE",
    "UNDYED_DIESEL",
    "DYED_DIESEL",
    "JET_FUEL",
    "AVIATION_GAS",
    "ETHANOL_E100",
    "BIODIESEL_B100",
]

RATE_CENTS_PER_GALLON = {
    "GASOLINE": Decimal("28.6"),
    "UNDYED_DIESEL": Decimal("30.9"),
    "DYED_DIESEL": Decimal("0.0"),
    "JET_FUEL": Decimal("5.0"),
    "AVIATION_GAS": Decimal("10.0"),
    "ETHANOL_E100": Decimal("28.6"),
    "BIODIESEL_B100": Decimal("30.9"),
}

LICENSE_TYPES = ["SUPPLIER", "DISTRIBUTOR", "BLENDER", "TRANSPORTER", "RETAILER"]
LICENSEE_STATUSES = ["PENDING_BOND", "ACTIVE", "SUSPENDED", "REVOKED"]
GROSS_NET_ELECTIONS = ["NET", "GROSS"]
RETAIL_CHANNELS = ["HIGHWAY", "MARINE", "FARM", "NOT_APPLICABLE"]

EXEMPTION_TYPES = ["GOVERNMENT", "AGRICULTURE", "EXPORT"]
CERT_PRODUCT_SET = {
    "GOVERNMENT": ["GASOLINE", "UNDYED_DIESEL"],
    "AGRICULTURE": ["UNDYED_DIESEL"],
    "EXPORT": ["GASOLINE", "UNDYED_DIESEL", "JET_FUEL", "AVIATION_GAS",
               "ETHANOL_E100", "BIODIESEL_B100"],
}

IMPOSITION_POINTS = ["TERMINAL_RACK", "DEFERRED_TO_PURCHASER", "NONE_EXEMPT"]

SCHEDULE_CODES = [
    "SCH_1_RECEIVED_TAX_PAID",
    "SCH_2_RECEIVED_TAX_UNPAID",
    "SCH_5_DELIVERED_TAX_COLLECTED",
    "SCH_6_EXEMPT_SALES",
    "SCH_7_EXPORTS",
    "SCH_10_DYED_SALES",
]
OUTBOUND_SCHEDULES = ["SCH_5_DELIVERED_TAX_COLLECTED", "SCH_6_EXEMPT_SALES",
                      "SCH_7_EXPORTS", "SCH_10_DYED_SALES"]
INBOUND_SCHEDULES = ["SCH_1_RECEIVED_TAX_PAID", "SCH_2_RECEIVED_TAX_UNPAID"]
TRANSACTION_TYPES = ["PURCHASE", "SALE", "EXPORT", "IMPORT", "BLEND", "TRANSFER"]

# Bonding (PRD 2.7)
BOND_MONTHS = 3
BOND_TYPE_MULTIPLIER = {
    "SUPPLIER": Decimal("1.0"),
    "DISTRIBUTOR": Decimal("1.0"),
    "BLENDER": Decimal("1.0"),
    "TRANSPORTER": Decimal("0.5"),
    "RETAILER": Decimal("0.25"),
}
BOND_SUSPENSION_MULTIPLIER = Decimal("2.0")
NEW_LICENSEE_ASSUMED_LIABILITY_CENTS = 500000
BOND_ROUNDING_STEP_CENTS = 100000
BOND_MIN_CENTS = 200000
BOND_MAX_CENTS = 100000000
BOND_MIN_INSTRUMENT_CENTS = 100000

# Returns (PRD 3.5)
DAILY_INTEREST_RATE = Decimal("0.00025")
PENALTY_FLOOR_CENTS = 5000
LARGE_LIABILITY_THRESHOLD_CENTS = 1000000
LARGE_LIABILITY_SURCHARGE_PCT = Decimal("0.05")

# Cross-matching (PRD 3.6)
DEFAULT_TOLERANCE_GALLONS = Decimal("5.00")
AUTO_ESCALATION_GALLONS = Decimal("10000.00")
MAX_INQUIRY_ROUNDS = 3
DISCREPANCY_DIRECTIONS = ["UNREPORTED_BY_PURCHASER", "OVERSTATED_BY_PURCHASER",
                          "MISSING_COUNTERPARTY_RETURN"]
OPEN_DISCREPANCY_STATUSES = ["OPEN", "INQUIRY_SENT", "RESPONSE_RECEIVED"]

# Refunds (PRD 3.7)
CLAIM_TYPES = ["OFF_ROAD", "PTO", "REFRIGERATION_UNIT", "EXPORT"]
EQUIPMENT_CLASSES = ["CONCRETE_MIXER", "REFUSE_PACKER", "BULK_TANKER_PUMP"]
PTO_ALLOCATION_PCT = {
    "CONCRETE_MIXER": Decimal("0.30"),
    "REFUSE_PACKER": Decimal("0.25"),
    "BULK_TANKER_PUMP": Decimal("0.15"),
}
REEFER_MONTHLY_CAP_GALLONS = Decimal("1500.00")
REEFER_REJECT_FACTOR = 10
MIN_REFUND_CENTS = 2000
REFUND_PRODUCT = "UNDYED_DIESEL"

# Roadside (PRD 3.8)
DYED_PENALTY_CENTS_PER_GALLON = Decimal("1000")
DYED_PENALTY_FLOOR_CENTS = 100000
DYED_SUSPENSION_THRESHOLD = 2

# Audit (PRD 3.9)
AUDIT_SELECTION_THRESHOLD = 60
AUDIT_PERIOD_BUFFER_MONTHS = 1
MAX_AUDIT_RESPONSE_ROUNDS = 2
EVASION_PENALTY_PCT = Decimal("0.50")
NON_EVASION_PENALTY_PCT = Decimal("0.10")
SELECTION_METHODS = ["RISK_SCORE", "CROSS_MATCH_ESCALATION", "ROADSIDE_REFERRAL"]
RISK_SCORE_VARIANTS = ["VARIANCE_WEIGHTED", "FREQUENCY_WEIGHTED"]
CASE_STATUSES = ["OPEN", "FIELDWORK", "PRELIM_FINDINGS", "TAXPAYER_RESPONSE",
                 "CLOSED"]
ASSESSMENT_STATUSES = ["NONE", "ISSUED", "PROTESTED", "FINAL", "ABATED"]

# Risk scoring (PRD 3.9)
LATE_POINTS_PER_UNIT = 8
LATE_POINTS_CAP = 24
DYED_POINTS_PER_UNIT = 15
DYED_POINTS_CAP = 30
GALLONS_PER_VARIANCE_POINT = Decimal("500")
VARIANCE_POINTS_CAP = 60
FREQUENCY_POINTS_PER_UNIT = 6
FREQUENCY_POINTS_CAP = 60
RISK_SCORE_CAP = 100

LEDGER_ENTRY_TYPES = ["RETURN_TAX", "RETURN_TAX_ADJUSTMENT", "PENALTY",
                      "INTEREST", "ASSESSMENT", "ABATEMENT", "REFUND",
                      "PAYMENT", "PENALTY_REVERSAL"]


def g2(value):
    """Quantize gallons to exactly two decimal places."""
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def cents(value):
    """Round a Decimal amount half up to a whole cent."""
    return int(Decimal(value).quantize(ONE, rounding=ROUND_HALF_UP))


def rate_cents(gallons, product_code):
    """gallons x per-product rate, rounded half up exactly once."""
    return cents(g2(gallons) * RATE_CENTS_PER_GALLON[product_code])


def round_half_up_int(value):
    """Round a Decimal half up to a whole number."""
    return int(Decimal(value).quantize(ONE, rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Bonding (PRD 2.7).
# --------------------------------------------------------------------------
def average_liability_cents(basis_returns):
    """floor(sum(tax_due_cents) / count); the assumed liability when empty."""
    if not basis_returns:
        return NEW_LICENSEE_ASSUMED_LIABILITY_CENTS
    total = sum(int(r["tax_due_cents"] or 0) for r in basis_returns)
    return total // len(basis_returns)


def required_bond_cents(avg_cents, license_type, suspended):
    """Ceil to the 100000-cent step first, then clamp into the statutory band."""
    multiplier = BOND_TYPE_MULTIPLIER[license_type]
    suspension = BOND_SUSPENSION_MULTIPLIER if suspended else Decimal("1.0")
    raw = Decimal(avg_cents) * Decimal(BOND_MONTHS) * multiplier * suspension
    steps = (raw / Decimal(BOND_ROUNDING_STEP_CENTS)).to_integral_value(
        rounding="ROUND_CEILING")
    rounded_up = int(steps) * BOND_ROUNDING_STEP_CENTS
    return min(BOND_MAX_CENTS, max(BOND_MIN_CENTS, rounded_up))


# --------------------------------------------------------------------------
# Return lateness, interest and penalty (PRD 3.5).
# --------------------------------------------------------------------------
def days_late_for(filed_at, due_at):
    """Whole days from due_at to filed_at, rounded UP; 0 when not late."""
    if filed_at <= due_at:
        return 0
    seconds = Decimal((filed_at - due_at).total_seconds())
    return int((seconds / Decimal(86400)).to_integral_value(
        rounding="ROUND_CEILING"))


def interest_for(tax_due_cents, days_late):
    if days_late == 0:
        return 0
    return cents(Decimal(tax_due_cents) * DAILY_INTEREST_RATE * Decimal(days_late))


def penalty_for(tax_due_cents, interest_cents, days_late):
    if days_late == 0:
        return 0
    subtotal = Decimal(tax_due_cents) + Decimal(interest_cents)
    if days_late <= 30:
        pct = Decimal("0.05")
    elif days_late <= 60:
        pct = Decimal("0.10")
    else:
        pct = Decimal("0.15")
    if subtotal >= Decimal(LARGE_LIABILITY_THRESHOLD_CENTS):
        pct = pct + LARGE_LIABILITY_SURCHARGE_PCT
    return max(PENALTY_FLOOR_CENTS, cents(subtotal * pct))


# --------------------------------------------------------------------------
# Risk scoring (PRD 3.9).
# --------------------------------------------------------------------------
def risk_scores(unreported_gallons, open_discrepancy_count, late_filing_count,
                dyed_violation_count):
    late_points = min(LATE_POINTS_CAP, LATE_POINTS_PER_UNIT * late_filing_count)
    dyed_points = min(DYED_POINTS_CAP, DYED_POINTS_PER_UNIT * dyed_violation_count)
    variance_points = min(
        VARIANCE_POINTS_CAP,
        round_half_up_int(Decimal(unreported_gallons) / GALLONS_PER_VARIANCE_POINT))
    frequency_points = min(
        FREQUENCY_POINTS_CAP,
        FREQUENCY_POINTS_PER_UNIT * open_discrepancy_count)
    variance_weighted = min(RISK_SCORE_CAP,
                            variance_points + late_points + dyed_points)
    frequency_weighted = min(RISK_SCORE_CAP,
                             frequency_points + late_points + dyed_points)
    return variance_weighted, frequency_weighted


# --------------------------------------------------------------------------
# Dyed-fuel penalty (PRD 3.8).
# --------------------------------------------------------------------------
def dyed_penalty_cents(gallons_in_tank, prior_positive_count):
    base = max(DYED_PENALTY_FLOOR_CENTS,
               cents(g2(gallons_in_tank) * DYED_PENALTY_CENTS_PER_GALLON))
    if prior_positive_count == 0:
        multiplier = Decimal("1.0")
    elif prior_positive_count == 1:
        multiplier = Decimal("2.0")
    else:
        multiplier = Decimal("3.0")
    return cents(Decimal(base) * multiplier)


# --------------------------------------------------------------------------
# Assessment amounts (PRD 3.9).
# --------------------------------------------------------------------------
def assessment_amounts(additional_tax_cents, evasion_indicator, clock,
                       period_due_at):
    pct = EVASION_PENALTY_PCT if evasion_indicator else NON_EVASION_PENALTY_PCT
    penalty = cents(Decimal(additional_tax_cents) * pct)
    if clock <= period_due_at:
        days = 0
    else:
        seconds = Decimal((clock - period_due_at).total_seconds())
        days = max(0, int((seconds / Decimal(86400)).to_integral_value(
            rounding="ROUND_FLOOR")))
    interest = cents(Decimal(additional_tax_cents) * DAILY_INTEREST_RATE *
                     Decimal(days))
    total = int(additional_tax_cents) + penalty + interest
    return penalty, interest, total, days
