"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock startup default (PRD §2.4)
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

# Move-out settlement forfeiture fees and surcharge (PRD §3.6)
TYPE_FEE_METAL_KEY_CENTS = 1500
TYPE_FEE_FOB_CENTS = 4500
TYPE_FEE_CARD_CENTS = 1501
ADMIN_SURCHARGE_PCT = 25
TRAILING_LOSS_WINDOW_DAYS = 30

# Building configuration defaults (PRD §3.1)
BUILDING_DEFAULTS = {
    "audit_retention_days": 90,
    "alert_escalation_minutes": 30,
    "vendor_badge_pool_max": 10,
    "default_propped_threshold_seconds": 120,
    "base_fee_cents": 15000,
    "per_door_fee_cents": 7500,
    "per_key_reissue_fee_cents": 2500,
    "emergency_surcharge_pct": 20,
    "business_open_utc": "08:00",
    "business_close_utc": "18:00",
}

# Issuance limits (PRD §3.2)
PERSON_ISSUED_CREDENTIAL_LIMIT = 5

# Days-of-week set for round-the-clock access groups
ALL_DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
