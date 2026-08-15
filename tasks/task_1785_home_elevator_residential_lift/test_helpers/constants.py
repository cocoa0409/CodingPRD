"""Domain thresholds and numeric constants from the PRD's calculation rules."""

# Default logical clock at startup (PRD §2.4).
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Maximum correctable pit/overhead shortfall, in inches (PRD §3.1/§3.2).
    "MAX_CORRECTABLE_INCHES": 12,
    # Landings included in every installation (PRD §3.2).
    "INCLUDED_FLOORS": 2,
    # Permit validity window, in days (PRD §3.3).
    "PERMIT_VALID_DAYS": 180,
    # Renewal grace window past expiration, in days (PRD §3.6).
    "RENEWAL_GRACE_DAYS": 90,
    # Inspector travel buffer, in minutes (PRD §3.5).
    "INSPECTOR_BUFFER_MINUTES": 45,
    # Ad-hoc entrapment SLA, in minutes (PRD §3.7).
    "ADHOC_ENTRAPMENT_SLA_MINUTES": 240,
}

RATES = {
    # Provisional quote components (PRD §3.2).
    "STRUCTURAL_BASE_FEE": 1500.00,
    "PIT_RATE_PER_INCH": 250.00,
    "OVERHEAD_RATE_PER_INCH": 150.00,
    "PER_FLOOR_FEE": 750.00,
    # Permit fee components (PRD §3.3).
    "BASE_PERMIT_FEE": 250.00,
    "PER_FLOOR_PERMIT_FEE": 50.00,
    "PLAN_REVIEW_RATE": 0.015,
    "ENERGY_RATE": 0.004,
    "ACCESSIBILITY_RATE": 0.007,
    # Settlement (PRD §3.8).
    "OVERAGE_SHARE": 0.50,
    "CHANGE_ORDER_MARKUP": 0.10,
    # Entrapment billing (PRD §3.7).
    "HALF_HOUR_RATE": 60.00,
    "AFTER_HOURS_MULTIPLIER": 1.5,
    "SLA_BREACH_CREDIT": 100.00,
    # Registration renewal fee (PRD §3.6).
    "BASE_RENEWAL_FEE": 175.00,
    "LATE_TIER1_MULTIPLIER": 1.25,
    "LATE_TIER2_MULTIPLIER": 1.50,
}

# Service-contract tier commercial terms (PRD §3.7).
TIER_TERMS = {
    "BASIC": {"annual_fee": 600.00, "included_visits": 1, "entrapment_sla_minutes": 240, "provisional_estimate": 300.00},
    "STANDARD": {"annual_fee": 1200.00, "included_visits": 2, "entrapment_sla_minutes": 120, "provisional_estimate": 150.00},
    "PREMIUM": {"annual_fee": 2400.00, "included_visits": 4, "entrapment_sla_minutes": 60, "provisional_estimate": 0.00},
}
ADHOC_PROVISIONAL_ESTIMATE = 450.00

TEST_DEFAULTS = {
    "OWNER_USER_ID": "u-own-1",
    "ADDRESS_LINE": "1 Pine St",
    "STATE_CODE": "CA",
    "AHJ_NAME": "Springfield AHJ",
}
