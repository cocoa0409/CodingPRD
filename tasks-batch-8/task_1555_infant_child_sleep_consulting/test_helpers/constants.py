"""Domain thresholds and pricing constants from the PRD's calculation rules."""

# Logical clock
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Package tier shape (PRD §3.4)
TIER_SHAPE = {
    "BASIC": {
        "duration_weeks": 2,
        "included_calls": 1,
        "included_messages": 5,
        "response_sla_hours": 48,
    },
    "STANDARD": {
        "duration_weeks": 4,
        "included_calls": 3,
        "included_messages": 15,
        "response_sla_hours": 24,
    },
    "PREMIUM": {
        "duration_weeks": 6,
        "included_calls": 6,
        "included_messages": 40,
        "response_sla_hours": 12,
    },
}

# Package pricing (PRD §3.4)
PRICING = {
    "BASIC_BASE_CENTS": 29900,
    "STANDARD_BASE_CENTS": 54900,
    "PREMIUM_BASE_CENTS": 89900,
    "NEWBORN_SURCHARGE_CENTS": 4950,
}

# SLA breach credit (PRD §3.6)
SLA_CREDIT_CENTS = 1000

# Refund valuation units (PRD §3.8)
REFUND_UNITS = {
    "CALL_VALUE_CENTS": 7500,
    "MESSAGE_VALUE_CENTS": 1200,
}

THRESHOLDS = {
    "COOLING_OFF_HOURS": 48,
    "FOLLOW_UP_WINDOW_DAYS": 180,
    "GUARANTEE_MIN_REVIEWED_LOGS": 14,
    "GUARANTEE_WINDOW_LOGS": 7,
    "GUARANTEE_MIN_MISSES": 4,
    "SESSION_BUFFER_MINUTES": 15,
    "SESSION_MIN_DURATION_MINUTES": 15,
    "SESSION_MAX_DURATION_MINUTES": 120,
}

TEST_DEFAULTS = {
    "CONSULTANT_FULL_NAME": "Dana Sleep",
    "GUARANTEE_GOAL_NIGHT_WAKINGS": 2,
    "CHILD_BIRTH_DATE": "2026-05-01",
    "PACKAGE_STARTS_ON": "2026-08-01",
}
