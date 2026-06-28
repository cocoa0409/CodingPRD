"""Domain thresholds — numeric constants drawn from the PRD's calculations.

Generic NON_EXISTENT_UUID comes from the framework barrel export.
"""

# alarm_priority_score (PRD 3.8)
SIGNAL_WEIGHT = {
    "MANUAL_BUTTON": 40,
    "FALL_DETECTED": 60,
    "BATTERY_CRITICAL": 20,
    "PERIODIC_CHECKIN_MISSED": 50,
}
FALL_BONUS = 30
BATTERY_BONUS = 25
ELEVATED_CUTOFF = 50
CRITICAL_CUTOFF = 80

# battery_health_class (PRD 3.5)
GOOD_CUTOFF = 40
LOW_CUTOFF = 20  # battery_health: below 20 is CRITICAL; device_test_result: < 20 FAIL_BATTERY

# equipment_damage_fee (PRD 3.11)
REPLACEMENT_COST_CENTS = {
    "PENDANT": 8000,
    "WRISTBAND": 9000,
    "MOBILE_GPS": 18000,
    "HOME_BASE": 12000,
}
GRADE_C_FRACTION = 0.5

# Monitoring-hold buffer (PRD 3.12)
HOLD_GAP_DAYS = 7

# Equipment-return deadline after finalization (PRD 3.7)
RETURN_DUE_BACK_DAYS = 14

# Default clock instants used throughout the suite (PRD 2.8 startup default 2026-05-01).
CLOCK_JUNE_1 = "2026-06-01T00:00:00Z"

# Test fixture defaults
TEST_DEFAULTS = {
    "BASIC_MONTHLY_FEE": 3000,
    "PLUS_MONTHLY_FEE": 4000,
    "PLUS_ADDON": 1500,
    "PREMIUM_MONTHLY_FEE": 6000,
    "PREMIUM_ADDON": 2000,
    "INTERVAL_DAYS": 30,
    "SLA_SECONDS": 60,
}
