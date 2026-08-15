"""Domain thresholds — numeric constants from PRD §3 calculation narratives."""

THRESHOLDS = {
    # HCE ownership prong: attributed ownership strictly greater than 5 percent (PRD §3.5)
    "HCE_OWNERSHIP_TEST_PCT": 5.0,
    # Coverage ratio inclusive floor (PRD §3.6 Coverage)
    "COVERAGE_THRESHOLD_PCT": 70.0,
    # ADP/ACP ceiling prongs (PRD §3.6 ADP)
    "ADP_BASIC_MULTIPLIER": 1.25,
    "ADP_ALT_ADDER_PCT": 2.0,
    "ADP_ALT_MULTIPLIER": 2.0,
    # Top-heavy strictly-greater threshold (PRD §3.6 Top-heavy)
    "TOP_HEAVY_THRESHOLD_PCT": 60.0,
    # Top-heavy minimum-contribution floor (PRD §3.6 Top-heavy)
    "TOP_HEAVY_FLOOR_PCT": 3.0,
    # Key-employee 1%-owner comp prong: $150,000 in cents (PRD §3.5)
    "KEY_ONE_PCT_OWNER_COMP_CENTS": 15000000,
    # Cafeteria 125 thresholds (PRD §3.6 Cafeteria)
    "CAFETERIA_ELIGIBILITY_THRESHOLD_PCT": 70.0,
    "KEY_CONCENTRATION_CEILING_PCT": 25.0,
    # Dependent care 55% average-benefits ratio (PRD §3.6 Dependent care)
    "DC_AVERAGE_BENEFITS_RATIO": 0.55,
    # Excise and gap-period constants (PRD §3.7)
    "EXCISE_RATE": 0.10,
    "DEEMED_EARNINGS_RATE": 0.07,
    "DAY_COUNT": 365,
    # Notice window minimum gap for mid-year amendments (PRD §3.8)
    "MIN_NOTICE_DAYS_BEFORE_YEAR_END": 30,
    # Ownership attribution cap (PRD §3.5)
    "OWNERSHIP_CAP_PCT": 100,
}

# Standard 2026 regulatory-limits row used by most fixtures (PRD §3.3 examples)
LIMITS_2026 = {
    "year_label": 2026,
    "hce_comp_threshold_cents": 15500000,
    "key_officer_comp_threshold_cents": 22000000,
    "sec402g_limit_cents": 2350000,
    "sec415_annual_additions_limit_cents": 6900000,
    "dependent_care_limit_cents": 500000,
}

LIMITS_2025 = {
    "year_label": 2025,
    "hce_comp_threshold_cents": 15000000,
    "key_officer_comp_threshold_cents": 21500000,
    "sec402g_limit_cents": 2300000,
    "sec415_annual_additions_limit_cents": 6800000,
    "dependent_care_limit_cents": 500000,
}

TEST_DEFAULTS = {
    "YEAR_LABEL": 2026,
    "YEAR_START": "2026-01-01",
    "YEAR_END": "2026-12-31",
    "COMP_DATE": "2026-06-30",
    # Fixed logical-clock default documented in PRD §2.5
    "CLOCK_DEFAULT_ISO": "2026-08-01T00:00:00Z",
}
