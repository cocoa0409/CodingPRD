"""Domain thresholds and pinned numeric constants used by the PRD calculations."""

# Regional price multipliers applied per line item, in basis points.
REGION_PRICE_MULTIPLIER_BP = {
    "NA": 10000,
    "EU": 11000,
    "LATAM": 6500,
    "APAC": 8500,
}

# Price-tier discounts applied per line item, in basis points.
TIER_DISCOUNT_BP = {
    "T1": 0,
    "T2": 500,
    "T3": 1200,
    "T4": 2000,
}

THRESHOLDS = {
    # Personalization
    "PERSONALIZATION_CAP_BP": 1500,
    # Offer fairness band
    "FAIRNESS_FLOOR_BP": 8000,
    "FAIRNESS_CEILING_BP": 15000,
    # Economy health bands
    "ECONOMY_HEALTHY_FLOOR_BP": 6000,
    "ECONOMY_WATCH_FLOOR_BP": 4000,
    "RATIO_CEILING_BP": 20000,
    # Retention bands
    "RETENTION_HEALTHY_FLOOR_BP": 9000,
    "RETENTION_AT_RISK_FLOOR_BP": 6000,
    "PACING_CEILING_BP": 20000,
    # Refund settlement
    "RESTOCK_TIER1_CEILING_MINOR": 1000,
    "RESTOCK_TIER2_CEILING_MINOR": 5000,
    "GOODWILL_SHARE_BP": 5000,
    "REFUND_WINDOW_DAYS": 14,
    # Responsible spending
    "ROLLING_SPEND_WINDOW_DAYS": 30,
    "MINOR_MONTHLY_CAP_MINOR": 5000,
    "SPEND_COOLDOWN_THRESHOLD_MINOR": 40000,
    "SPEND_LOCK_THRESHOLD_MINOR": 75000,
    # Storefront window conflicts
    "SKU_COOLDOWN_HOURS": 24,
    # Cadence
    "ROLLBACK_DEBT_DAYS": 3,
    "CADENCE_DEBT_LIMIT_DAYS": 14,
}

# The logical clock always starts here.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# Canonical season window used across setups: 2026-08-01 -> 2026-10-30 (90 days).
TEST_DEFAULTS = {
    "SEASON_CODE": "S7",
    "SEASON_TITLE": "Season 7 Tidebreak",
    "SEASON_STARTS_AT": "2026-08-01T00:00:00Z",
    "SEASON_ENDS_AT": "2026-10-30T00:00:00Z",
    "SEASON_PLANNED_EPISODE_COUNT": 6,
    "SEASON_TARGET_XP_TOTAL": 9000,
    "SEASON_PASS_PRICE_MINOR": 1000,
}

# Operator user ids threaded through the opaque roles.
OPERATOR_IDS = {
    "ContentProducer": "u_producer_1",
    "EconomyDesigner": "u_designer_1",
    "EconomyDesignerAlt": "u_designer_2",
    "LiveOpsCommander": "u_liveops_1",
    "ComplianceOfficer": "u_compliance_1",
    "ComplianceOfficerAlt": "u_compliance_2",
}
