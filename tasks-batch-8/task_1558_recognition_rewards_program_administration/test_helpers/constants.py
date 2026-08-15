"""Domain thresholds and numeric constants from the PRD's calculation rules."""

# Logical clock startup default (PRD §2.5): the server boots at this instant.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Budget posture (basis points, floor division; boundaries inclusive)
    "RESTRICTED_THRESHOLD_BP": 8500,
    "EXHAUSTED_THRESHOLD_BP": 10000,
    # Nomination submission gate: policy cap while budget posture is RESTRICTED
    "RESTRICTED_APPROVAL_CAP_POINTS": 500,
    # Recognition tiers (inclusive lower bounds on lifetime_granted_points)
    "SILVER_AT": 1000,
    "GOLD_AT": 5000,
    "PLATINUM_AT": 20000,
    # Tax: federal supplemental-wage tier and FICA
    "FEDERAL_SUPPLEMENTAL_RATE": 0.22,
    "FEDERAL_SUPPLEMENTAL_RATE_HIGH": 0.37,
    "SUPPLEMENTAL_TIER_THRESHOLD_CENTS": 100000000,
    "FICA_RATE": 0.0765,
    # De-minimis annual exclusion cap (integer cents, all-or-nothing)
    "DEMINIMIS_ANNUAL_CAP_CENTS": 10000,
    # Chargeback forfeiture recovery rate
    "FORFEITURE_RECOVERY_RATE": 0.5,
    # Vendor ship-date selector lookahead (calendar days)
    "SHIP_LOOKAHEAD_CALENDAR_DAYS": 45,
    # Redemption order quantity bounds
    "MIN_QUANTITY": 1,
    "MAX_QUANTITY": 5,
    # Single-order abuse flag trigger (points_total strictly greater)
    "REDEMPTION_ANOMALY_POINTS": 50000,
    # tax_year valid range
    "TAX_YEAR_MIN": 2000,
    "TAX_YEAR_MAX": 2100,
    # Return window after delivery (days, inclusive)
    "RETURN_WINDOW_DAYS": 14,
    # Award lifetime (months)
    "AWARD_EXPIRY_MONTHS": 12,
    # Utilization-weighted accrual curve (months 1-11: 0.07, month 12: 0.23)
    "UTILIZATION_CURVE": {
        1: 0.07, 2: 0.07, 3: 0.07, 4: 0.07, 5: 0.07, 6: 0.07,
        7: 0.07, 8: 0.07, 9: 0.07, 10: 0.07, 11: 0.07, 12: 0.23,
    },
    # Participation analytics defaults
    "ANALYTICS_DEFAULT_WINDOW_DAYS": 90,
    "ANALYTICS_TOP_PERCENT": 0.05,
    # Program defaults (PRD §3.1)
    "DEFAULT_VELOCITY_LIMIT_PER_7_DAYS": 5,
    "DEFAULT_DUPLICATE_WINDOW_DAYS": 30,
    "DEFAULT_NOMINATION_REVIEW_SLA_DAYS": 14,
    "DEFAULT_RESTOCKING_FEE_PERCENT": 20,
}

TEST_DEFAULTS = {
    "POINT_COST_RATE_CENTS": 0.5,
    "MAX_POINTS_PER_NOMINATION": 10000,
    "STATE_RATE_MAP": {"CA": 0.093, "TX": 0.0},
    "BUDGET_WINDOW_START": "2026-01-01",
    "BUDGET_WINDOW_END": "2027-01-01",
    "ALLOCATED_POINTS": 100000,
    "ITEM_WINDOW_START": "2026-01-01T00:00:00Z",
    "ITEM_WINDOW_END": "2027-01-01T00:00:00Z",
}
