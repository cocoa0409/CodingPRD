"""Domain thresholds and fixed configuration from the PRD."""

DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

THRESHOLDS = {
    "BILLING_PERIOD_DAYS": 30,
    "TRIAL_DAYS": 14,
    "PAST_DUE_GRACE_DAYS": 10,
    "REFRESH_INTERVAL_DAYS": 365,
    "REFRESH_DUE_BAND_DAYS": 15,
    "REFRESH_GRACE_DAYS": 30,
    "APPRAISAL_VALIDITY_DAYS": 1095,
    "APPRAISAL_REQUIRED_THRESHOLD_CENTS": 1_000_000,
    "SCHEDULE_REQUIRED_THRESHOLD_CENTS": 500_000,
    "APPRAISAL_BUFFER_HOURS": 24,
    "MAX_APPEALS_PER_LINE": 2,
    "SHARE_MAX_DURATION_DAYS": 90,
    "SHARE_DEFAULT_ACCESS_CAP": 10,
    "PACKAGE_VALIDITY_DAYS": 180,
    "FAIR_DIVISION_TOLERANCE_PCT": 5.0,
    "SELL_DISPOSITION_COST_PCT": 12.0,
    "MAX_ITEM_QUANTITY": 999,
    "MIN_ITEM_QUANTITY": 1,
    "MONTH_DAYS_FOR_AGE": 30,
}

CLAIM_MIN_EVIDENCE_TIER = "PHOTO_SERIAL"
PACKAGE_MIN_EVIDENCE_TIER = "PHOTO_ONLY"

EVIDENCE_TIER_RANK = {
    "NONE": 0,
    "PHOTO_ONLY": 1,
    "PHOTO_SERIAL": 2,
    "DOCUMENTED": 3,
}

SUBSCRIPTION_TIERS = {
    "BASIC": {
        "monthly_fee_cents": 900,
        "max_items": 50,
        "max_assets": 200,
        "max_asset_bytes": 2_000_000_000,
        "included_appraisal_credits": 0,
        "included_packages_per_period": 1,
        "tier_rank": 1,
    },
    "PLUS": {
        "monthly_fee_cents": 2900,
        "max_items": 500,
        "max_assets": 2_000,
        "max_asset_bytes": 20_000_000_000,
        "included_appraisal_credits": 2,
        "included_packages_per_period": 4,
        "tier_rank": 2,
    },
    "ESTATE": {
        "monthly_fee_cents": 7900,
        "max_items": 5_000,
        "max_assets": 20_000,
        "max_asset_bytes": 200_000_000_000,
        "included_appraisal_credits": 6,
        "included_packages_per_period": 12,
        "tier_rank": 3,
    },
}

# Endpoints that stay callable while a household is READ_ONLY (PRD 2.7 Gate 1).
WRITE_GATE_EXCLUSION_LIST = [
    "POST /vault/subscriptions/{subscription_id}/billing-event",
    "POST /vault/subscriptions/{subscription_id}/reinstate",
    "POST /vault/subscriptions/{subscription_id}/attest-refresh",
    "POST /vault/claims",
    "POST /vault/claims/{claim_id}/lines",
    "POST /vault/claims/{claim_id}/submit",
    "POST /vault/claims/{claim_id}/withdraw",
    "POST /vault/claim-lines/{claim_line_id}/adjudicate",
    "POST /vault/claim-lines/{claim_line_id}/appeal",
    "POST /vault/claims/{claim_id}/settle",
    "POST /vault/share-grants/{share_grant_id}/revoke",
    "POST /_clock/set_current_utc",
]

# Endpoints blocked while a household is RESTRICTED (PRD 2.7 Gate 2).
RESTRICTED_GATE_BLOCK_LIST = [
    "POST /vault/packages/{package_id}/generate",
    "POST /vault/share-grants",
]

TEST_DEFAULTS = {
    "CARRIER_NAME": "Northwind Mutual",
    "CHECKSUM": "sha-test-0001",
    "PHOTO_BYTES": 9000,
    "SERIAL_PLATE_BYTES": 4000,
    "RECEIPT_BYTES": 3000,
}
