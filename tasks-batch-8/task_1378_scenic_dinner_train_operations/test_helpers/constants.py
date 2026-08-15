"""Domain thresholds and defaults — numeric constants from PRD §2.5, §2.6, §2.7, §3."""

THRESHOLDS = {
    # Fares (PRD §2.6)
    "FARE_COACH_CENTS": 6000,
    "FARE_FIRST_CLASS_CENTS": 11000,
    "FARE_DINING_CENTS": 15000,
    "BASE_SURGE_BP": 10000,
    "MIN_HOLIDAY_SURGE_BP": 12000,
    "MAX_SURGE_BP": 20000,
    # Galley provisioning (PRD §3.7)
    "UNITS_PER_MEAL": 3,
    "BUFFER_PCT": 0.10,
    # Refund window (PRD §3.6)
    "FULL_REFUND_HOURS": 48,
    # Clock sweep (PRD §2.5)
    "HOLD_MINUTES": 45,
    "RAIN_CHECK_VALID_DAYS": 365,
    # Crew coverage (PRD §3.4)
    "SERVERS_PER_DINING_CAR": 2,
    # Dining selector (PRD §3.5)
    "TABLE_SEATS": 4,
    # Maintenance turnaround buffer (PRD §2.7)
    "TURNAROUND_BUFFER_MINUTES": 60,
    # Agreement shape floors (PRD §3.1)
    "MIN_SLOT_MINUTES_FLOOR": 30,
    "MIN_TRAINS_PER_DAY": 1,
}

TEST_DEFAULTS = {
    # Startup value of the logical clock (PRD §2.5)
    "CLOCK_START": "2026-08-01T00:00:00Z",
    # Canonical test service date / slot window (10:00-13:00)
    "SERVICE_DATE": "2026-10-15",
    "SLOT_START_MINUTE": 600,
    "SLOT_END_MINUTE": 780,
    # Agreement validity covering all of 2026
    "VALID_FROM": "2026-01-01",
    "VALID_UNTIL": "2026-12-31",
    "MAX_TRAINS_PER_DAY": 3,
    "MIN_SLOT_MINUTES": 60,
    # Crew cert validity comfortably beyond the service dates in play
    "CERT_EXPIRES_ON": "2027-06-01",
}
