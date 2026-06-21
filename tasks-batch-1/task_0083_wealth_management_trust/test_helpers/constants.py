"""Domain thresholds — numeric constants from PRD calculations (§2, §3.9).

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Compressed four-bracket trust/estate income-tax schedule (PRD §3.9), in cents.
TAX_BRACKETS = {
    "B1": 310_000,    # first 310,000 cents at R1
    "B2": 1_115_000,  # up to 1,115,000 cents at R2
    "B3": 1_520_000,  # up to 1,520,000 cents at R3
    "R1": 0.10,
    "R2": 0.24,
    "R3": 0.35,
    "R4": 0.37,
}

# GST tax rate (PRD §3.9).
GST_RATE = 0.40

# Mandatory buffer gap between successive terms of one trustee on one trust (PRD §3.2).
TRUSTEE_GAP_DAYS = 30

# Statutory lifetime GST exemption the platform seeds when omitted (PRD §3.1).
DEFAULT_GST_EXEMPTION_TOTAL_CENTS = 1_399_000_000

# Pagination defaults (PRD §2.3).
PAGINATION = {"limit_default": 10, "limit_min": 1, "limit_max": 100, "offset_default": 0}

# Common ISO 8601 datetime literals reused across multi-year fixtures.
TERM_START = "2025-01-01T00:00:00.000Z"
TERM_END = "2030-01-01T00:00:00.000Z"
PERIOD_START = "2025-01-01T00:00:00.000Z"
PERIOD_END = "2026-01-01T00:00:00.000Z"
