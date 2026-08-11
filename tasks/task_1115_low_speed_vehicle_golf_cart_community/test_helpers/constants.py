"""Domain thresholds and numeric constants from the PRD's calculation rules
(PR D §3.5 registration fee, §3.6 late fee / renewal score, §3.8 charging fee
and fleet late fine, §3.9 points standing) and community defaults (§3.1)."""

# Community creation defaults (PRD §3.1)
COMMUNITY_DEFAULTS = {
    "MIN_DRIVER_AGE": 16,
    "INSURANCE_REQUIRED": True,
    "FLEET_PROGRAM_ENABLED": False,
    "MIN_LIABILITY_COVERAGE_CENTS": 10000000,
    "RENEWAL_WINDOW_DAYS": 60,
    "LATE_GRACE_DAYS": 90,
}

# annual_registration_fee constants (PRD §3.5)
FEE_CONSTANTS = {
    "BASE_FEE_GOLF_CART": 7500,
    "BASE_FEE_LSV": 15000,
    "EQUIP_RATE_PROVISIONAL": 0.02,
    "EQUIP_RATE_FINALIZED": 0.025,
    "MULT_CAP": 1.20,
    "SEAT_FREE": 4,
    "SEAT_SURCHARGE": 500,
    "FLEET_DISCOUNT_PCT": 0.10,
}

# late_renewal_fee constants (PRD §3.6)
LATE_FEE_CONSTANTS = {
    "TIER_BOUNDARY_CENTS": 10000,
    "TIER_A_LATE": [1500, 3000, 6000],
    "TIER_B_LATE": [2500, 5000, 10000],
    "BAND_1_MAX_DAYS": 30,
    "BAND_2_MAX_DAYS": 60,
    "TOTAL_CAP_MULTIPLE": 2,
}

# inspection_total_score constants (PRD §3.4)
INSPECTION_CONSTANTS = {
    "WEIGHT_PCT": {
        "headlights": 16.67,
        "brake_lights": 16.67,
        "turn_signals": 13.33,
        "horn": 6.67,
        "mirrors": 10.00,
        "windshield": 10.00,
        "seatbelts": 16.66,
        "reflectors": 10.00,
    },
    "PASS_THRESHOLD": 70.00,
}

# renewal_compliance_score constants (PRD §3.6)
RENEWAL_SCORE_CONSTANTS = {
    "PASS_THRESHOLD": 70,
    "RECENCY_FULL_DAYS": 180,
    "WINDOW_DAYS": 365,
    "AGED_FILED_DAYS": 30,
}

# holder_points_standing constants (PRD §3.9)
POINTS_CONSTANTS = {
    "POINTS_WINDOW_DAYS": 730,
    "PROBATION_THRESHOLD": 4,
    "BAR_THRESHOLD": 12,
}

# charging_fee constants (PRD §3.8)
CHARGING_CONSTANTS = {
    "MIN_CHARGE_CENTS": 200,
    "BUFFER_MINUTES": 15,
}

# fleet late fine (PRD §3.8)
FLEET_CONSTANTS = {
    "LATE_FINE_PER_DAY_CENTS": 500,
}

# The logical clock starts here at server startup (PRD §2.4)
STARTUP_CLOCK = "2026-05-01T00:00:00Z"

# Default birth date for a driver who is exactly 16 at the startup clock
DEFAULT_BIRTH_DATE = "2010-05-01"

TEST_DEFAULTS = {
    "REGISTRATION_YEAR": 2026,
    "STATION_RATE_CENTS_PER_MIN": 10,
    "POLICY_COVERAGE_CENTS": 10000000,
    "POLICY_EFFECTIVE_DATE": "2026-01-01",
    "POLICY_EXPIRY_DATE": "2027-12-31",
}
