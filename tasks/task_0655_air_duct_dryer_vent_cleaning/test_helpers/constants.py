"""Domain thresholds — numeric constants from the PRD calculations."""

# Pricing / discount thresholds
MULTI_SYSTEM_THRESHOLD = 2          # active_system_count at/above which the duct discount applies

# Duration calculation
SETUP_MINUTES = 20
DUCT_MINUTES_PER_LINE = 35
SANITIZE_MINUTES_PER_LINE = 15
DRYER_MINUTES_PER_LINE = 25
ADDON_MINUTES_EACH = 10
LARGE_HOME_SQFT = 3000
BIG_HOME_FACTOR = 1.25

# Contamination risk score
SEVERITY_WEIGHT = 8
DENSITY_WEIGHT = 2
RISK_CEILING = 100
REFERRAL_RISK_THRESHOLD = 40

# Completion / route geometry
MIN_AFTER_PHOTOS = 1
BUFFER_MINUTES = 15

# Referral lifetime
REFERRAL_TTL_DAYS = 30

# Logical clock default at server startup
DEFAULT_CLOCK = "2026-04-01T00:00:00Z"

# Shared PricingConfig price book used across the design indices (cents / fractions).
SHARED_CONFIG = {
    "duct_base_cents": 12000,
    "duct_per_system_cents": 4000,
    "dryer_vent_flat_cents": 9000,
    "sanitize_per_system_cents": 5000,
    "addon_sanitizer_cents": 3000,
    "addon_uv_cents": 7000,
    "addon_coil_cents": 2500,
    "multi_system_discount_pct": 0.10,
    "plan_member_discount_pct": 0.15,
    "tax_pct": 0.08,
}

# A syntactically valid UUID that is guaranteed not to exist in a fresh DB.
NON_EXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
