"""Domain thresholds — numeric constants from PRD §3 calculations."""

THRESHOLDS = {
    # Daily admission pricing (PRD §3.2)
    "CHILD_MULTIPLIER": 0.60,          # CHILD patrons pay 60 percent of the base
    "SENIOR_MULTIPLIER": 0.75,         # SENIOR patrons pay 75 percent
    "CHILD_AGE_MAX": 17,               # under 18 is CHILD
    "SENIOR_AGE_MIN": 62,              # 62 or older is SENIOR
    # Rental quote (PRD §3.7)
    "RENTAL_BASE_PER_HOUR_CENTS": 15000,
    "NON_RESIDENT_RENTAL_MULTIPLIER": 1.50,
    "INCLUDED_PARTY_SIZE": 25,
    "EXTRA_PERSON_CENTS": 300,
    "OVERTIME_PER_15MIN_CENTS": 5000,
    "OVERTIME_BLOCK_MINUTES": 15,
    # Staffing (PRD §3.5)
    "BATHERS_PER_ADDITIONAL_GUARD": 25,
    "BASE_GUARD_COUNT": 2,
    "BASE_GUARD_BATHER_MAX": 50,
    "SHIFT_NO_SHOW_GRACE_MINUTES": 15,
    # Chemistry (PRD §3.3)
    "FC_MIN": 1.0,
    "FC_MAX": 5.0,
    "PH_MIN": 7.2,
    "PH_MAX": 7.8,
    "CC_WARN": 0.4,
    # Rain check (PRD §3.4)
    "FULL_REFUND_ELAPSED_MIN": 60,
    "PRO_RATA_FRACTION": 0.50,
    # Rental cancellation (PRD §3.7)
    "CANCEL_FEE_FRACTION": 0.25,
    "CANCEL_FEE_WINDOW_HOURS": 72,
    # Discipline (PRD §3.8)
    "BAN_DAYS_PER_MAJOR": 30,
    "BAN_STRIKE_THRESHOLD": 3,
}

TEST_DEFAULTS = {
    "DEFAULT_CLOCK": "2026-05-01T00:00:00Z",
}
