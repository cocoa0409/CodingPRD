"""Domain thresholds — numeric constants from PRD calculations."""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Calculation constants (PRD §3.5–§3.6)
# ---------------------------------------------------------------------------

# Personal-postal threshold: dutiable value <= this AND trade_mode==B2C →
# PERSONAL_POSTAL tax mode. Inclusive comparison (PRD §3.6:
# "The boundary is inclusive: a declaration whose dutiable value is exactly
# 5,000.00 CNY still qualifies for personal-postal mode").
PERSONAL_POSTAL_THRESHOLD_CNY_MINOR: int = 500_000  # 5,000.00 CNY in fen

# Statutory exemption: postal_total <= this → total_tax_cny_minor = 0.
# Inclusive (PRD §3.6: "a candidate total of exactly 50.00 CNY is exempt").
POSTAL_EXEMPTION_CNY_MINOR: int = 5_000  # 50.00 CNY in fen

# Deductive method (PRD §3.5)
DEDUCTION_RATIO_BPS: int = 1500          # 15% deduction
RETAIL_MARKUP_NUM: int = 125             # retail = transaction * 125 / 100
RETAIL_MARKUP_DEN: int = 100

# Computed method (PRD §3.5)
LOGISTICS_PER_KG_MINOR: int = 5000       # 50.00 CNY per kg in fen
COMPUTED_UPLIFT_BPS: int = 1000          # 10% uplift

# Classification suggestion (PRD §3.2)
KEYWORD_WEIGHT: float = 0.7
DESCRIPTION_WEIGHT: float = 0.3
MIN_RELEVANCE_SCORE: float = 0.20
SUGGESTION_TOP_N: int = 3

# Submission rework limit (PRD §3.4)
SUBMISSION_REWORK_LIMIT: int = 3

# Payment notice expiry window (PRD §3.8)
PAYMENT_NOTICE_DUE_HOURS: int = 168
PAYMENT_NOTICE_DUE_SECONDS: int = 168 * 3600

# Inspection slot duration (PRD §3.7)
INSPECTION_SLOT_MINUTES: int = 60
INSPECTION_SLOT_SECONDS: int = 60 * 60

# Basis-point / micro denominators
BPS_DENOMINATOR: int = 10_000
MICRO_DENOMINATOR: int = 1_000_000


# ---------------------------------------------------------------------------
# Pagination defaults (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_DEFAULT_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Test calendar baseline — clock-driving fixtures pin operations relative
# to this fixed instant.
# ---------------------------------------------------------------------------
TEST_BASELINE_DATE_ISO: str = "2026-01-01"
TEST_BASELINE_INSTANT_ISO: str = "2026-01-15T10:00:00Z"


# ---------------------------------------------------------------------------
# Reference document type codes (PRD §3.10 supporting_documents)
# ---------------------------------------------------------------------------
DOC_TYPE_RETURN: str = "SHIPMENT_RETURN_RECEIPT"
DOC_TYPE_CANCELLATION: str = "CANCELLATION_AGREEMENT"
DOC_TYPE_AMENDMENT: str = "AMENDMENT_DECISION"


__all__ = [
    "PERSONAL_POSTAL_THRESHOLD_CNY_MINOR",
    "POSTAL_EXEMPTION_CNY_MINOR",
    "DEDUCTION_RATIO_BPS",
    "RETAIL_MARKUP_NUM",
    "RETAIL_MARKUP_DEN",
    "LOGISTICS_PER_KG_MINOR",
    "COMPUTED_UPLIFT_BPS",
    "KEYWORD_WEIGHT",
    "DESCRIPTION_WEIGHT",
    "MIN_RELEVANCE_SCORE",
    "SUGGESTION_TOP_N",
    "SUBMISSION_REWORK_LIMIT",
    "PAYMENT_NOTICE_DUE_HOURS",
    "PAYMENT_NOTICE_DUE_SECONDS",
    "INSPECTION_SLOT_MINUTES",
    "INSPECTION_SLOT_SECONDS",
    "BPS_DENOMINATOR",
    "MICRO_DENOMINATOR",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "TEST_BASELINE_DATE_ISO",
    "TEST_BASELINE_INSTANT_ISO",
    "DOC_TYPE_RETURN",
    "DOC_TYPE_CANCELLATION",
    "DOC_TYPE_AMENDMENT",
]
