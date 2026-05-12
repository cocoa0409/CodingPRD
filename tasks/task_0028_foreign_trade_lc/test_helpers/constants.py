"""Domain thresholds — numeric constants from PRD calculations and rules."""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_DEFAULT_OFFSET: int = 0


# ---------------------------------------------------------------------------
# LC drafting (PRD §3.2)
# ---------------------------------------------------------------------------
DEFAULT_DISCREPANCY_FEE_MINOR: int = 7500       # PRD §3.2: default 7,500 minor units = 75.00
DEFAULT_PRESENTATION_PERIOD_DAYS: int = 21      # PRD §3.2 / §3.6: UCP600 default 21
USANCE_TENOR_DAYS_ALLOWED = (30, 60, 90, 120, 180)  # PRD §3.2
TOLERANCE_PCT_MIN: float = 0.0                  # PRD §3.2
TOLERANCE_PCT_MAX: float = 10.0                 # PRD §3.2


# ---------------------------------------------------------------------------
# Refusal / examination windows (PRD §3.5, §3.6, §3.7)
# ---------------------------------------------------------------------------
EXAMINATION_DEADLINE_BANKING_DAYS: int = 5      # PRD §3.5 / §3.6
REFUSAL_WINDOW_BANKING_DAYS: int = 5            # PRD §3.7 / §2.8 (UCP600 art.16(d)/(f))
RETURN_WINDOW_BANKING_DAYS: int = 7             # PRD §3.7


# ---------------------------------------------------------------------------
# Negotiation discount (PRD §3.8)
# ---------------------------------------------------------------------------
NEGOTIATION_RATE_BPS: int = 350                 # PRD §3.8: 3.50% annualised
NEGOTIATION_RATE_DENOM: int = 10_000            # basis-points denominator
NEGOTIATION_DAYS_TO_REIMBURSEMENT: int = 7      # PRD §3.8
NEGOTIATION_DAYS_DENOM: int = 360               # PRD §3.8


# ---------------------------------------------------------------------------
# Expiry alerts (PRD §3.10)
# ---------------------------------------------------------------------------
EXPIRY_ALERT_T_MINUS_15_DAYS: int = 15
EXPIRY_ALERT_T_MINUS_5_DAYS: int = 5
EXPIRED_CLOSE_GRACE_DAYS: int = 30              # PRD §3.10: EXPIRED → CLOSED at expiry+30


# ---------------------------------------------------------------------------
# Required documents (PRD §3.2)
# ---------------------------------------------------------------------------
DOCUMENT_TYPE_VALUES = (
    "COMMERCIAL_INVOICE",
    "BILL_OF_LADING",
    "PACKING_LIST",
    "INSURANCE_POLICY",
    "CERTIFICATE_OF_ORIGIN",
)
MANDATORY_REQUIRED_DOCUMENTS = ("COMMERCIAL_INVOICE", "BILL_OF_LADING")

DISCREPANCY_CODE_VALUES = (
    "MISSING_DOCUMENT",
    "LATE_PRESENTATION",
    "LATE_SHIPMENT",
    "AMOUNT_MISMATCH",
    "DESCRIPTION_MISMATCH",
    "INCONSISTENT_DOCS",
    "EXPIRED_LC",
    "CURRENCY_MISMATCH",
)


# ---------------------------------------------------------------------------
# Test default scalars — non-binding values that satisfy field constraints.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "CURRENCY": "USD",
    "AMOUNT_MINOR_UNITS": 100_000,        # 1,000.00 USD
    "TOLERANCE_PCT": 0,
    "DEFAULT_LC_TYPE": "SIGHT",
    "USANCE_TENOR": 60,
    "COUNTRY_CODE_APPLICANT": "US",
    "COUNTRY_CODE_BENEFICIARY": "CN",
    "COUNTRY_CODE_BANK": "GB",
}


def negotiation_discount_minor_units(base_minor_units: int) -> int:
    """PRD §3.8: discount = floor(base * 350/10000 * 7/360).

    Pure-Python integer-floor implementation that mirrors the PRD pin
    'discount captures funds-time-value: rate is 350 basis points
    annualised (3.50%) and assumed time to reimbursement is 7 days; the
    multiplicative result floors to an integer in minor units'.
    """
    numerator = base_minor_units * NEGOTIATION_RATE_BPS * NEGOTIATION_DAYS_TO_REIMBURSEMENT
    denominator = NEGOTIATION_RATE_DENOM * NEGOTIATION_DAYS_DENOM
    return numerator // denominator


def lc_drawing_cap_minor_units(amount_minor_units: int, tolerance_pct: float) -> int:
    """PRD §2.5 / §3.5: cap = floor(amount * (100 + tolerance_pct) / 100)."""
    # Use integer arithmetic to avoid float drift on round numbers.
    # tolerance_pct may be 0..10, possibly fractional in principle; the
    # test factories always pass integer values so we round defensively.
    numerator = amount_minor_units * (100 + tolerance_pct)
    return int(numerator // 100)


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "DEFAULT_DISCREPANCY_FEE_MINOR",
    "DEFAULT_PRESENTATION_PERIOD_DAYS",
    "USANCE_TENOR_DAYS_ALLOWED",
    "TOLERANCE_PCT_MIN",
    "TOLERANCE_PCT_MAX",
    "EXAMINATION_DEADLINE_BANKING_DAYS",
    "REFUSAL_WINDOW_BANKING_DAYS",
    "RETURN_WINDOW_BANKING_DAYS",
    "NEGOTIATION_RATE_BPS",
    "NEGOTIATION_RATE_DENOM",
    "NEGOTIATION_DAYS_TO_REIMBURSEMENT",
    "NEGOTIATION_DAYS_DENOM",
    "EXPIRY_ALERT_T_MINUS_15_DAYS",
    "EXPIRY_ALERT_T_MINUS_5_DAYS",
    "EXPIRED_CLOSE_GRACE_DAYS",
    "DOCUMENT_TYPE_VALUES",
    "MANDATORY_REQUIRED_DOCUMENTS",
    "DISCREPANCY_CODE_VALUES",
    "TEST_DEFAULTS",
    "negotiation_discount_minor_units",
    "lc_drawing_cap_minor_units",
]
