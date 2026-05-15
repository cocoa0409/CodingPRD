"""Domain thresholds and constants from the PRD.

Only constants whose numeric value is stated verbatim by PRD prose are
hard-coded here. PRD-referenced constants whose numeric value the
prose does NOT pin (e.g., KYC_VALIDITY_DAYS, MAX_REVISION_ROUNDS,
MAX_PARTIAL_PREPAYMENTS, AML_BLACKLIST_THRESHOLD, FRAUD_RISK_THRESHOLD,
SOFT_TO_HARD_REMINDER_THRESHOLD, ON_SITE_THRESHOLD_CENTS,
CENTRAL_REGISTRY_THRESHOLD_CENTS, MAX_DUE_DATE_DAYS,
THIRD_PARTY_PASS_FLOOR, FRAUD_PENALTY) are intentionally absent — tests
that rely on those thresholds must drive the system to the boundary
observably (e.g., loop until the implementation rejects) rather than
hard-code a particular value.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Maximum supplier tier (PRD §3.2)
# "the maximum allowed tier is the MAX_EXTENSION_TIER system constant,
#  which is currently four."
# ---------------------------------------------------------------------------
MAX_EXTENSION_TIER = 4


# ---------------------------------------------------------------------------
# APR clamp window (PRD §3.5)
# "The floor is 300 basis points and the ceiling is 2400 basis points."
# ---------------------------------------------------------------------------
APR_FLOOR_BPS = 300
APR_CEILING_BPS = 2400


# ---------------------------------------------------------------------------
# Platform fees (PRD §3.6)
# "the principal multiplied by the PLATFORM_FEE_BPS system constant
#  (50 basis points) divided by ten thousand"
# ---------------------------------------------------------------------------
PLATFORM_FEE_BPS = 50


# ---------------------------------------------------------------------------
# Capital-flow / goods-flow tolerance (PRD §3.9)
# "the CAPITAL_GOODS_TOLERANCE_BPS system constant (currently 500 basis
#  points, or 5.00%)"
# ---------------------------------------------------------------------------
CAPITAL_GOODS_TOLERANCE_BPS = 500


# ---------------------------------------------------------------------------
# Pricing tables (PRD §3.5)
# Base APR per financing mode and per core-enterprise risk-rating
# adjustment, supplier risk-rating adjustment, and tier penalty.
# ---------------------------------------------------------------------------
MODE_BASE_BPS = {
    "FACTORING": 800,
    "REVERSE_FACTORING": 600,
    "DYNAMIC_DISCOUNTING": 500,
    "RECEIVABLE_PLEDGE": 700,
}

CORE_RISK_ADJ_BPS = {
    "AAA": -150,
    "AA": -100,
    "A": 0,
    "BBB": 100,
    "BB": 250,
}

SUPPLIER_RISK_ADJ_BPS = {
    "LOW": 0,
    "MEDIUM": 100,
    "HIGH": 250,
}

# PRD §3.5: "50 basis points multiplied by one less than the supplier's
# tier_to_core, so tier 1 contributes zero, tier 2 contributes 50, tier
# 3 contributes 100, and tier 4 contributes 150."
TIER_PENALTY_PER_LEVEL_BPS = 50


# ---------------------------------------------------------------------------
# Composite risk-score weights (PRD §3.5)
# "weights 0.5 for KYC, 0.3 for AML, and 0.2 for tier"
# ---------------------------------------------------------------------------
W_KYC = 0.5
W_AML = 0.3
W_TIER = 0.2

# PRD §3.5 reverse-factoring CoreEnterprise-rating to KYC-factor mapping:
# "AAA maps to 1.0, AA to 0.9, A to 0.8, BBB to 0.7, and BB to 0.5"
REVERSE_FACTORING_CORE_KYC_MAP = {
    "AAA": 1.0,
    "AA": 0.9,
    "A": 0.8,
    "BBB": 0.7,
    "BB": 0.5,
}

# PRD §3.5 composite-score bucketing thresholds:
# ">= 0.80 LOW; >= 0.60 MEDIUM; >= 0.40 HIGH; < 0.40 REJECT"
COMPOSITE_LOW = 0.80
COMPOSITE_MEDIUM = 0.60
COMPOSITE_HIGH = 0.40


# ---------------------------------------------------------------------------
# Overdue penalty-interest rates by aging bucket (PRD §3.8)
# "DPD_1_30 accrues at 1200, DPD_31_60 at 1800, DPD_61_90 at 2400,
#  and DPD_OVER_90 at 3000."
# ---------------------------------------------------------------------------
PENALTY_BPS_BY_BUCKET = {
    "DPD_1_30": 1200,
    "DPD_31_60": 1800,
    "DPD_61_90": 2400,
    "DPD_OVER_90": 3000,
}


# ---------------------------------------------------------------------------
# Aging bucket boundaries (PRD §3.8)
# "a dpd from 1 through 30 inclusive yields DPD_1_30, from 31 through 60
#  inclusive yields DPD_31_60, from 61 through 90 inclusive yields
#  DPD_61_90, and 91 and above yields DPD_OVER_90"
# ---------------------------------------------------------------------------
DPD_BOUNDARIES = {
    "DPD_1_30": (1, 30),
    "DPD_31_60": (31, 60),
    "DPD_61_90": (61, 90),
    "DPD_OVER_90": (91, None),
}


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
SECONDS_PER_DAY = 86_400
DAYS_PER_YEAR = 365


# ---------------------------------------------------------------------------
# Unified Social Credit Code regex (PRD §2.8)
# "globally unique 18-character uppercase alphanumeric strings matching
#  the regular expression for the Unified Social Credit Code"
# ---------------------------------------------------------------------------
USCC_PATTERN = r"^[0-9A-Z]{18}$"


# ---------------------------------------------------------------------------
# Test defaults — give individual tests common, varied baseline values.
# ---------------------------------------------------------------------------
TEST_DEFAULTS: dict = {
    # Core enterprise
    "CE_LEGAL_NAME": "Test Anchor Buyer Co., Ltd.",
    "CE_CREDIT_LINE": 10_000_000_00,    # 10,000,000.00 in cents
    "CE_LOW_CREDIT_LINE": 1_000,        # very small, for insufficient-line tests
    "ERP_ENDPOINT": "https://erp.example.com/webhook",

    # Supplier
    "SUP_LEGAL_NAME": "Test Supplier Co., Ltd.",
    "SUP_BANK_ACCOUNT": "6225000011112222",

    # PayableConfirmation
    "INVOICE_NUMBER": "INV-2026-0001",
    "CONTRACT_NUMBER": "CN-2026-0001",
    "PC_AMOUNT_CENTS": 1_000_000,        # 10,000.00

    # Receivable
    "INVOICE_DOC_ID": "doc-invoice-001",
    "CONTRACT_DOC_ID": "doc-contract-001",

    # FinancingApplication
    "REQUESTED_AMOUNT_CENTS": 1_000_000,
    "TERM_DAYS": 90,
    "SUPPORTING_DOC_IDS": ["doc-waybill-001", "doc-customs-001"],

    # Verification
    "WAYBILL_DOC_ID": "doc-waybill-001",
    "CUSTOMS_DOC_ID": "doc-customs-001",
    "THIRD_PARTY_SCORE_PASS": 0.90,
    "THIRD_PARTY_SCORE_FAIL": 0.10,

    # Reasons (free text)
    "REVOKE_REASON": "trade-dispute",
    "REJECT_REASON": "Credit risk above tolerance.",
    "REVISION_NOTES": "Please attach additional logistics documentation.",
    "SUSPEND_REASON": "Material adverse change in core enterprise standing.",
    "WRITE_OFF_REASON": "Debtor insolvent; deemed uncollectible.",

    # Funder
    "FUNDER_ACCOUNT_ID": "funder-account-001",

    # Central registry
    "CENTRAL_REGISTRY_FILING_NO": "REG-2026-0001",
}


__all__ = [
    "MAX_EXTENSION_TIER",
    "APR_FLOOR_BPS",
    "APR_CEILING_BPS",
    "PLATFORM_FEE_BPS",
    "CAPITAL_GOODS_TOLERANCE_BPS",
    "MODE_BASE_BPS",
    "CORE_RISK_ADJ_BPS",
    "SUPPLIER_RISK_ADJ_BPS",
    "TIER_PENALTY_PER_LEVEL_BPS",
    "W_KYC",
    "W_AML",
    "W_TIER",
    "REVERSE_FACTORING_CORE_KYC_MAP",
    "COMPOSITE_LOW",
    "COMPOSITE_MEDIUM",
    "COMPOSITE_HIGH",
    "PENALTY_BPS_BY_BUCKET",
    "DPD_BOUNDARIES",
    "SECONDS_PER_DAY",
    "DAYS_PER_YEAR",
    "USCC_PATTERN",
    "TEST_DEFAULTS",
]
