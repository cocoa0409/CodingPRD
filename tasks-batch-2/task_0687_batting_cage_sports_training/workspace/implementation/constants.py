"""All numeric constants, read verbatim from SCAFFOLD calculations / PRD section 3."""

# booking_quote / booking_charge
SLOT_MINUTES = 10
MACHINE_SURCHARGE_CENTS = {"WHEEL": 800, "ARM": 1200, "SOFT_TOSS": 300}
PARTY_BASE_CENTS = 15000
PARTY_PER_GUEST_CENTS = 1200
TIER_DISCOUNT_PCT = {"NONE": "0.0", "BRONZE": "0.10", "GOLD": "0.25"}

# booking_charge peak window (minute-of-day, UTC)
PEAK_START_MIN = 1020  # 17:00 UTC
PEAK_END_MIN = 1260    # 21:00 UTC
PEAK_MULTIPLIER = "1.5"

# machine_status thresholds
DEGRADE_AT = 5000
OOS_AT = 10000
PITCHES_PER_SESSION = 1000

# facility_posture
CLOSE_THRESHOLD = 2

# member minutes / strikes / check-in
MEMBER_MINUTE_CAP = 1200
MAX_STRIKES = 3
EARLY_CHECKIN_MIN = 30

# waiver validity
WAIVER_VALID_DAYS = 365

# refund policy
REFUND_CUTOFF_MIN = 120
REFUND_FORFEIT_PCT = "0.5"
