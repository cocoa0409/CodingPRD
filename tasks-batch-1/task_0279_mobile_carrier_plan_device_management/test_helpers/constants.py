"""Domain thresholds — numeric constants from the PRD calculations (§3.10).

Group-discount tiers, overage tier-1 default cap, and the milli-cent unit are
the table-lookup and unit constants the money math depends on. NON_EXISTENT_UUID
comes from the framework.
"""

# Multi-line group-discount table (PRD §3.10): keyed on active_line_count.
GROUP_DISCOUNT = {
    "TIER1_PCT": 0.00,   # <= 1 active line
    "TIER2_PCT": 0.05,   # exactly 2
    "TIER3_PCT": 0.10,   # exactly 3
    "TIER4_PCT": 0.15,   # exactly 4
    "TIER5PLUS_PCT": 0.20,  # >= 5 (cap)
    "CAP_LINES": 5,
}

# Overage units / defaults (PRD §3.1, §3.10).
MILLI_CENTS_PER_CENT = 1000
DEFAULT_OVERAGE_TIER1_CAP_MB = 5120

# A standard "Plus" plan payload used across many setups.
PLAN_DEFAULTS = {
    "monthly_fee_cents": 7000,
    "included_data_mb": 20480,
    "overage_tier1_cap_mb": 5120,
    "overage_tier1_rate_milli_cents": 1000,   # 1 cent / MB at tier 1
    "overage_tier2_rate_milli_cents": 500,    # 0.5 cent / MB at tier 2
}

# Allowed installment terms (PRD §3.6).
ALLOWED_TERM_MONTHS = [12, 24, 36]

# A non-existent UUID literal usable for FK/path 404/422 probes.
SAMPLE_MISSING_UUID = "00000000-0000-4000-8000-000000000000"
