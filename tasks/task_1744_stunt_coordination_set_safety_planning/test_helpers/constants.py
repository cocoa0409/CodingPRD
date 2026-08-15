"""Domain thresholds and constants stated in the PRD (§2.5, §3)."""

# Logical clock startup default (PRD §2.5)
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# Risk scoring (PRD §3.2)
HAZARD_WEIGHT = {
    "PYRO": 6,
    "FIRE": 5,
    "HEIGHT": 4,
    "VEHICLE": 4,
    "AERIAL": 4,
    "WATER": 3,
    "FIGHT": 2,
}
MITIGATION_CREDIT = -3
LOCK_THRESHOLD = 26
SCREENING_BANDS = {
    "LOW": (1, 5),
    "MEDIUM": (6, 11),
    "HIGH": (12, 19),
    "CRITICAL": (20, 25),
}

# Rehearsal quota by declared risk category (PRD §3.2)
QUOTA_BY_CATEGORY = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
SPECIAL_EQUIPMENT_TYPES = {"PYRO_DEVICE", "CRANE"}

# Hazard-pay negotiation (PRD §3.7)
CATEGORY_CAP_PCT = {"LOW": 0.15, "MEDIUM": 0.35, "HIGH": 0.60, "CRITICAL": 1.00}
UNION_FLOOR_CENTS = 15000
SPECIAL_EQUIPMENT_CAP_SURCHARGE_CENTS = 25000
TAKE_BONUS_CENTS = 50000
MAX_NEGOTIATION_ROUNDS = 6

# Budget authority check (PRD §3.7)
RESERVE_PCT = 0.10

# Insurance endorsement premium tiers (PRD §3.1)
PREMIUM_TIER1_MAX_CENTS = 100000000
PREMIUM_TIER2_MAX_CENTS = 500000000

# Facility buffer between meetings (PRD §3.4)
MEETING_FACILITY_BUFFER_SECONDS = 1800

# Stoppage cooldown before a lift is permitted (PRD §3.8)
STOPPAGE_COOLDOWN_SECONDS = 86400

# Common timestamps (relative to the logical clock default)
DEFAULT_ISSUED_AT = "2026-01-01T00:00:00Z"
DEFAULT_CERT_EXPIRY = "2027-01-01T00:00:00Z"
DEFAULT_EXEC_START = "2026-08-05T00:00:00Z"
DEFAULT_EXEC_END = "2026-08-06T00:00:00Z"
REHEARSAL_DAY = "2026-08-02"
MEETING_DAY = "2026-08-03"
