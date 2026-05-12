"""Domain thresholds and tuning constants from PRD §2 and §3.

Numeric values are the ones stated in PRD prose; tests use these so
threshold magic numbers are not duplicated across the suite.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Time precision (PRD §2.8, §2.9, §3.7)
# ---------------------------------------------------------------------------
WORKING_DAY_SECONDS = 28800   # PRD §2.8: 'a working day is exactly eight hours, i.e. 28,800 seconds'
DAY_SECONDS = 86400           # PRD §3.10: certificate validity uses 86,400 seconds per day
ESCALATION_PCT = 150          # PRD §3.7: 'pct at or above 150'


# ---------------------------------------------------------------------------
# MatterVersion limits (PRD §3.1, §3.2)
# ---------------------------------------------------------------------------
STATUTORY_MIN_DAYS = 1
STATUTORY_MAX_DAYS = 365
COMMITTED_MIN_DAYS = 1
WARNING_PCT_MIN = 50
WARNING_PCT_MAX = 99
WARNING_PCT_DEFAULT = 80
MAX_CORRECTION_ROUNDS_MIN = 1
MAX_CORRECTION_ROUNDS_MAX = 5
MAX_CORRECTION_ROUNDS_DEFAULT = 2
CORRECTION_WINDOW_DAYS_MIN = 1
CORRECTION_WINDOW_DAYS_MAX = 30
CORRECTION_WINDOW_DAYS_DEFAULT = 7


# ---------------------------------------------------------------------------
# Field length / format limits (PRD §3.1, §3.3)
# ---------------------------------------------------------------------------
DEPARTMENT_CODE_MIN_LEN = 3
DEPARTMENT_CODE_MAX_LEN = 32
MATTER_CODE_MIN_LEN = 4
MATTER_CODE_MAX_LEN = 64
VERSION_LABEL_MIN_LEN = 1
VERSION_LABEL_MAX_LEN = 32
MATERIAL_TEMPLATE_CODE_MIN_LEN = 4
MATERIAL_TEMPLATE_CODE_MAX_LEN = 64
CERTIFICATE_TEMPLATE_CODE_MIN_LEN = 4
CERTIFICATE_TEMPLATE_CODE_MAX_LEN = 64
VERIFICATION_CODE_LEN = 16


# ---------------------------------------------------------------------------
# Certificate template (PRD §3.3, §3.10)
# ---------------------------------------------------------------------------
VALIDITY_DAYS_MIN = 0
VALIDITY_DAYS_DEFAULT = 0


# ---------------------------------------------------------------------------
# Fee breakdown constants (PRD §3.11)
# ---------------------------------------------------------------------------
HANDLING_RATE_BP = 200          # PRD §3.11: 'handling-rate basis points (200 basis points, i.e., 2.00%)'
OVERHEAD_RATE_BP = 500          # PRD §3.11: 'overhead-rate basis points (500 basis points, i.e., 5.00%)'
SURCHARGE_PER_ROUND_CENTS = 500 # PRD §3.11: 'per-round surcharge constant of 500 cents (i.e., 5.00 yuan per round)'
CAP_SURCHARGE_CENTS = 1000      # PRD §3.11: 'capped at the surcharge cap of 1,000 cents (i.e., 10.00 yuan)'
SURCHARGE_TIER_BOUNDARY = 2     # rounds <= 2 use multiplier; > 2 uses cap


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "WORKING_DAY_SECONDS",
    "DAY_SECONDS",
    "ESCALATION_PCT",
    "STATUTORY_MIN_DAYS",
    "STATUTORY_MAX_DAYS",
    "COMMITTED_MIN_DAYS",
    "WARNING_PCT_MIN",
    "WARNING_PCT_MAX",
    "WARNING_PCT_DEFAULT",
    "MAX_CORRECTION_ROUNDS_MIN",
    "MAX_CORRECTION_ROUNDS_MAX",
    "MAX_CORRECTION_ROUNDS_DEFAULT",
    "CORRECTION_WINDOW_DAYS_MIN",
    "CORRECTION_WINDOW_DAYS_MAX",
    "CORRECTION_WINDOW_DAYS_DEFAULT",
    "DEPARTMENT_CODE_MIN_LEN",
    "DEPARTMENT_CODE_MAX_LEN",
    "MATTER_CODE_MIN_LEN",
    "MATTER_CODE_MAX_LEN",
    "VERSION_LABEL_MIN_LEN",
    "VERSION_LABEL_MAX_LEN",
    "MATERIAL_TEMPLATE_CODE_MIN_LEN",
    "MATERIAL_TEMPLATE_CODE_MAX_LEN",
    "CERTIFICATE_TEMPLATE_CODE_MIN_LEN",
    "CERTIFICATE_TEMPLATE_CODE_MAX_LEN",
    "VERIFICATION_CODE_LEN",
    "VALIDITY_DAYS_MIN",
    "VALIDITY_DAYS_DEFAULT",
    "HANDLING_RATE_BP",
    "OVERHEAD_RATE_BP",
    "SURCHARGE_PER_ROUND_CENTS",
    "CAP_SURCHARGE_CENTS",
    "SURCHARGE_TIER_BOUNDARY",
]
