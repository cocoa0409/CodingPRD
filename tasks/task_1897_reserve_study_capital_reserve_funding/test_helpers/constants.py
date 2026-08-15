"""Domain thresholds and shared fixtures values from the PRD (§2.4–§3.9)."""

# PRD §3.2 — site-visit spacing and cadence arithmetic.
SITE_VISIT_MIN_GAP_DAYS = 30
DAYS_PER_YEAR = 365

# PRD §3.4 / §3.9 — projection horizon (years indexed 0..29, balances 1..30).
PROJECTION_HORIZON_YEARS = 30

# PRD §3.6 — reconciliation auto-match tolerance constants.
VARIANCE_TOLERANCE_FLAT_CENTS = 500
VARIANCE_TOLERANCE_PCT = 0.10

# PRD §3.4 — THRESHOLD floor peak ratio (one half of the largest outflow).
THRESHOLD_PEAK_RATIO = 0.5

# PRD §2.4 — the logical clock before any client sets it.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Canonical state rules used across the suite.
RULE_CA = {
    "state_code": "CA",
    "min_percent_funded_pct": 50,
    "allowed_plan_types": ["BASELINE", "THRESHOLD", "FULL"],
    "site_visit_interval_years": 3,
    "disclosure_deadline_days": 30,
    "annual_update_required": True,
}
RULE_NV = {
    "state_code": "NV",
    "min_percent_funded_pct": 0,
    "allowed_plan_types": ["BASELINE", "THRESHOLD", "FULL"],
    "site_visit_interval_years": 3,
    "disclosure_deadline_days": 30,
    "annual_update_required": False,
}
RULE_TX = {
    "state_code": "TX",
    "min_percent_funded_pct": 0,
    "allowed_plan_types": ["BASELINE"],
    "site_visit_interval_years": 5,
    "disclosure_deadline_days": 60,
    "annual_update_required": False,
}

# Standard two-component inventory used by the calculation tests:
# FFB = round(100000*3/5) + round(50000*3/4) = 60000 + 37500 = 97500.
F1_COMPONENTS = [
    {
        "name": "Roof",
        "category": "ROOFING",
        "useful_life_years": 5,
        "remaining_useful_life_years": 2,
        "current_replacement_cost_cents": 100000,
        "is_included_in_funding": True,
    },
    {
        "name": "Paving",
        "category": "PAVING",
        "useful_life_years": 4,
        "remaining_useful_life_years": 1,
        "current_replacement_cost_cents": 50000,
        "is_included_in_funding": True,
    },
]

# Default completed-visit date: 32 days before the default clock reading,
# inside every cadence window used by the suite.
DEFAULT_VISIT_DATE = "2026-06-30"
