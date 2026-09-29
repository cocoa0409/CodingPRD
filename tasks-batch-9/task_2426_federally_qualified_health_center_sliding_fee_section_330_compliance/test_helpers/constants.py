"""Domain thresholds and defaults drawn from the PRD's stated rules."""

# ---------------------------------------------------------------------------
# The logical compliance clock (PRD §2.5)
# ---------------------------------------------------------------------------

CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Thresholds the PRD states explicitly
# ---------------------------------------------------------------------------

THRESHOLDS = {
    # PRD §2.3 — pagination bounds
    "PAGINATION_LIMIT_DEFAULT": 10,
    "PAGINATION_LIMIT_MIN": 1,
    "PAGINATION_LIMIT_MAX": 100,
    "PAGINATION_OFFSET_MIN": 0,
    # PRD §2.6 / §3.4 — an income verification expires exactly 365 days after
    # its effective_date and the window is closed at both ends.
    "VERIFICATION_WINDOW_DAYS": 365,
    # PRD §3.3 — 365 elapsed days is still CURRENT, 366 is REVIEW_DUE.
    "REVIEW_DUE_ELAPSED_DAYS": 365,
    # PRD §3.2 — the patient-majority clauses
    "MIN_SEATED_BOARD_COUNT": 3,
    "MAX_SEATED_BOARD_COUNT": 25,
    "PATIENT_MAJORITY_PCT": 51.00,
    "PATIENT_SEAT_RECENCY_MONTHS": 24,
    # PRD §3.1 — the default nominal fee cap when registration omits it
    "DEFAULT_NOMINAL_FEE_CAP_CENTS": 2500,
    # PRD §3.5 — PPS rate multipliers
    "ADDITIONAL_SERVICE_MULTIPLIER": 0.85,
    "INTERMITTENT_SITE_MULTIPLIER": 0.90,
    # Loop caps (PRD §3.4, §3.8, §3.9)
    "RESUBMIT_ROUND_CAP": 3,
    "REVISION_ROUND_CAP": 3,
    "CAP_SUBMIT_ROUND_CAP": 2,
    "UDS_RETURN_ROUND_CAP": 3,
    # PRD §3.1 — guideline year range
    "GUIDELINE_YEAR_MIN": 2000,
    "GUIDELINE_YEAR_MAX": 2100,
    # PRD §2.6 — the four uniform data system reporting bands
    "UDS_BAND_1_UPPER": 100.00,
    "UDS_BAND_2_UPPER": 150.00,
    "UDS_BAND_3_UPPER": 200.00,
}

# ---------------------------------------------------------------------------
# Values reused across setups
# ---------------------------------------------------------------------------

TEST_DEFAULTS = {
    "PPS_BASE_RATE_CENTS": 18000,
    "MEDICARE_UPPER_LIMIT_CENTS": 15000,
    "NOMINAL_FEE_CAP_CENTS": 2500,
    "NOMINAL_FEE_CENTS": 2500,
    "FPG_YEAR": 2026,
    "EFFECTIVE_START": "2026-01-01T00:00:00Z",
    "EFFECTIVE_END": "2027-01-01T00:00:00Z",
    "GUIDELINE_2025_BASE_CENTS": 1560000,
    "GUIDELINE_2025_INCREMENT_CENTS": 550000,
    "GUIDELINE_2026_BASE_CENTS": 1620000,
    "GUIDELINE_2026_INCREMENT_CENTS": 570000,
}

# The five-band ladder used by most sliding-fee setups: 0/100/138/175/200.
FIVE_BAND_LADDER = [
    {
        "tier_label": "NOMINAL_FULL",
        "fpg_min_pct": 0,
        "fpg_max_pct": 100,
        "discount_kind": "NOMINAL",
        "sort_order": 1,
    },
    {
        "tier_label": "PARTIAL_A",
        "fpg_min_pct": 100,
        "fpg_max_pct": 138,
        "discount_kind": "PERCENT_DISCOUNT",
        "discount_pct": 0.80,
        "sort_order": 2,
    },
    {
        "tier_label": "PARTIAL_B",
        "fpg_min_pct": 138,
        "fpg_max_pct": 175,
        "discount_kind": "PERCENT_DISCOUNT",
        "discount_pct": 0.60,
        "sort_order": 3,
    },
    {
        "tier_label": "PARTIAL_C",
        "fpg_min_pct": 175,
        "fpg_max_pct": 200,
        "discount_kind": "PERCENT_DISCOUNT",
        "discount_pct": 0.40,
        "sort_order": 4,
    },
    {
        "tier_label": "FULL_CHARGE",
        "fpg_min_pct": 200,
        "fpg_max_pct": None,
        "discount_kind": "NONE",
        "sort_order": 5,
    },
]

# The minimal well-formed ladder: two bands, 0/100.
TWO_BAND_LADDER = [
    {
        "tier_label": "NOMINAL_FULL",
        "fpg_min_pct": 0,
        "fpg_max_pct": 100,
        "discount_kind": "NOMINAL",
        "sort_order": 1,
    },
    {
        "tier_label": "FULL_CHARGE",
        "fpg_min_pct": 100,
        "fpg_max_pct": None,
        "discount_kind": "NONE",
        "sort_order": 2,
    },
]
