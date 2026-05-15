"""Domain thresholds and numeric constants from the PRD.

These constants encode the numeric values PRD §3 pins into calculations
(tariff tier breakpoints, VAT rates, consumption-tax table, FX tables,
authenticity threshold, declared-value-review threshold, late-interest
boundaries, amendment cap).
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# PRD §2.7 / §3.8 — tariff tier breakpoints (base_value in settlement currency).
# ---------------------------------------------------------------------------
TIER_BREAKPOINT_LOW = 10000.00   # <= 10000 → 1.00 ; > 10000 → 1.05
TIER_BREAKPOINT_HIGH = 50000.00  # > 50000 → 1.10
TIER_FACTOR_BASE = 1.00
TIER_FACTOR_MID = 1.05
TIER_FACTOR_HIGH = 1.10

# ---------------------------------------------------------------------------
# PRD §3.8 — MFN (general) tariff rate table.
# Key 'default' is the catch-all per jurisdiction; '8517' is the named override.
# ---------------------------------------------------------------------------
MFN_RATE_TABLE = {
    "CN": {"default": 0.10, "8517": 0.05},
    "US": {"default": 0.08, "8517": 0.04},
    "EU": {"default": 0.12, "8517": 0.06},
    "JP": {"default": 0.09, "8517": 0.045},
    "GB": {"default": 0.10, "8517": 0.05},
}

# PRD §3.8 — preferential trade-agreement rate table.
FTA_RATE_TABLE = {
    "RCEP":   {"CN": {"default": 0.05, "8517": 0.02},
               "JP": {"default": 0.04, "8517": 0.02}},
    "USMCA":  {"US": {"default": 0.03, "8517": 0.015}},
    "EU_GSP": {"EU": {"default": 0.06, "8517": 0.03}},
    "CPTPP":  {"JP": {"default": 0.035, "8517": 0.015}},
}

# ---------------------------------------------------------------------------
# PRD §3.8 — VAT rate table.
# ---------------------------------------------------------------------------
VAT_RATE_TABLE = {
    "CN": 0.13,
    "US": 0.00,
    "EU": 0.21,
    "JP": 0.10,
    "GB": 0.20,
}

# ---------------------------------------------------------------------------
# PRD §3.8 — consumption-tax table (only specific (jurisdiction, hs_prefix4) pairs).
# Boundary: ct_base < 100 → 0 ; ct_base >= 100 → taxed.
# ---------------------------------------------------------------------------
CONSUMPTION_TAX_TABLE = {
    ("CN", "2208"): 0.20,
    ("JP", "2208"): 0.15,
    ("US", "2402"): 0.30,
    ("GB", "2402"): 0.25,
}
CT_BASE_THRESHOLD = 100.00

# ---------------------------------------------------------------------------
# PRD §3.9 — agreement-currency → declared-currency FX table.
# ---------------------------------------------------------------------------
AGREEMENT_FX_TABLE = {
    ("USD", "USD"): 1.00,
    ("USD", "CNY"): 7.20,
    ("USD", "EUR"): 0.92,
    ("USD", "JPY"): 150.0,
    ("USD", "GBP"): 0.78,
    ("CNY", "CNY"): 1.00,
    ("CNY", "USD"): 0.139,
    ("EUR", "EUR"): 1.00,
    ("EUR", "USD"): 1.08,
    ("JPY", "JPY"): 1.00,
    ("JPY", "USD"): 0.0067,
    ("GBP", "GBP"): 1.00,
    ("GBP", "USD"): 1.28,
}

# ---------------------------------------------------------------------------
# PRD §3.4 — authenticity scoring constants.
# ---------------------------------------------------------------------------
AUTHENTICITY_WEIGHT_TOTAL = 0.5
AUTHENTICITY_WEIGHT_CURRENCY = 0.3
AUTHENTICITY_WEIGHT_URI = 0.2
AUTHENTICITY_ACCEPT_THRESHOLD = 0.70
URI_SOFT_SCORE = 0.5
TOTAL_MATCH_TOLERANCE = 0.005  # 0.5% per PRD §3.4

# ---------------------------------------------------------------------------
# PRD §3.3 — declared-value review reference prices (in settlement currency).
# Boundary: deviation <= 0.25 → ACCEPTED ; > 0.25 → FLAGGED.
# ---------------------------------------------------------------------------
DECLARED_VALUE_REFERENCE_PRICES = {
    ("CN", "8517"): 800.00,
    ("US", "8517"): 800.00,
    ("EU", "8517"): 800.00,
    ("JP", "8517"): 800.00,
    ("GB", "8517"): 800.00,
    ("CN", "2208"): 50.00,
}
DECLARED_VALUE_DEVIATION_THRESHOLD = 0.25

# ---------------------------------------------------------------------------
# PRD §3.6 — query response window (48h after response_received_at).
# ---------------------------------------------------------------------------
QUERY_DEADLINE_HOURS = 48

# ---------------------------------------------------------------------------
# PRD §3.10 — reimbursement window (7 days after advance_paid_at).
# ---------------------------------------------------------------------------
REIMBURSEMENT_WINDOW_DAYS = 7
DAY_SECONDS = 86400

# ---------------------------------------------------------------------------
# PRD §3.11 — amendment cap.
# ---------------------------------------------------------------------------
AMENDMENT_CAP = 3

# ---------------------------------------------------------------------------
# PRD §3.5 — restricted HS prefixes (for IMPORT_LICENSE requirement).
# ---------------------------------------------------------------------------
RESTRICTED_HS_PREFIXES_LICENSE = ("28", "29")
DANGEROUS_HS_PREFIXES = ("2208", "2402", "2710")

# ---------------------------------------------------------------------------
# Sensible factory defaults.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "AGREEMENT_CURRENCY": "USD",
    "DECLARED_CURRENCY": "USD",
    "SETTLEMENT_CURRENCY": "CNY",
    "DAILY_RATE_BPS": 100,  # 1%/day
    "JURISDICTION": "CN",
    "HS_CODE": "85171200",     # 8 digits, prefix 8517 (electronics)
    "HS_PREFIX": "8517",
    "COUNTRY_OF_ORIGIN": "JP",
    "DEFAULT_BUDGET": 0.0,
    "WAREHOUSE_CODE": "BOND-001",
}


__all__ = [
    "TIER_BREAKPOINT_LOW",
    "TIER_BREAKPOINT_HIGH",
    "TIER_FACTOR_BASE",
    "TIER_FACTOR_MID",
    "TIER_FACTOR_HIGH",
    "MFN_RATE_TABLE",
    "FTA_RATE_TABLE",
    "VAT_RATE_TABLE",
    "CONSUMPTION_TAX_TABLE",
    "CT_BASE_THRESHOLD",
    "AGREEMENT_FX_TABLE",
    "AUTHENTICITY_WEIGHT_TOTAL",
    "AUTHENTICITY_WEIGHT_CURRENCY",
    "AUTHENTICITY_WEIGHT_URI",
    "AUTHENTICITY_ACCEPT_THRESHOLD",
    "URI_SOFT_SCORE",
    "TOTAL_MATCH_TOLERANCE",
    "DECLARED_VALUE_REFERENCE_PRICES",
    "DECLARED_VALUE_DEVIATION_THRESHOLD",
    "QUERY_DEADLINE_HOURS",
    "REIMBURSEMENT_WINDOW_DAYS",
    "DAY_SECONDS",
    "AMENDMENT_CAP",
    "RESTRICTED_HS_PREFIXES_LICENSE",
    "DANGEROUS_HS_PREFIXES",
    "TEST_DEFAULTS",
]
