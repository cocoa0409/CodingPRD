"""Domain thresholds and constants from the PRD's calculation rules (section 3)."""

# own_vs_rent (PRD 3.6): wear rate and fixed ownership / admin fees
WEAR_RATE_CENTS_PER_HOUR = 900
FIXED_OWNERSHIP_CENTS_PER_DAY = 4200
EXTERNAL_RENTAL_ADMIN_CENTS_PER_DAY = 1500

# utilization_rate (PRD 3.6): expected day
EXPECTED_HOURS_PER_DAY = 8

# redeployment_scan (PRD 3.7): idle-alert window
IDLE_WINDOW_DAYS = 5

# damage_chargeback (PRD 3.8): abuse multiplier and cap
ABUSE_MULTIPLIER_BP = 15000
CHARGE_CAP_CENTS = 5000000

# transport_overlap (PRD 3.5): lowboy turnaround buffer
TURNAROUND_HOURS = 4

# Logical clock default (PRD 2.10)
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Common test defaults
TEST_DEFAULTS = {
    "DAILY_RATE_CENTS": 10000,
    "EXTERNAL_DAILY_RATE_CENTS": 12000,
    "WEEKEND_MULTIPLIER_BP": 5000,
    "IDLE_DAY_MULTIPLIER_BP": 5000,
    "SERVICE_INTERVAL_HOURS": 10000,
    "IDLE_ALERT_UTILIZATION_BP": 3000,
    "EXPECTED_LIFE_HOURS": 10000,
    "SALVAGE_VALUE_CENTS": 500000,
    "PROJECT_BUDGET_CENTS": 100000000,
    "ACQUISITION_COST_CENTS": 10000000,
    "USEFUL_LIFE_MONTHS": 60,
}
