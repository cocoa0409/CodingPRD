"""Domain thresholds and pinned constants (PRD §2.9, §3.1-§3.9)."""

# Logical clock default (PRD §2.4)
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# Quote computation (PRD §3.3)
MOBILIZATION_FLAT_CENTS = 15000

# Test outcome thresholds (PRD §3.4)
TIGHTNESS_PASS_GPH = 0.100          # inclusive pass bound
SPILL_HOLD_MINUTES = 5              # inclusive pass bound
OVERFILL_MAX_PCT = 95.0             # inclusive pass bound
INSTANT_OFF_THRESHOLD_MV = -850     # inclusive pass bound
POLARIZATION_SHIFT_MIN_MV = 100     # inclusive pass bound

# Scheduling (PRD §3.3)
TANK_STABILIZATION_HOURS = 8

# Tank registration (PRD §3.1)
MANUAL_GAUGING_MAX_CAPACITY_GALLONS = 2000

# Test-schedule intervals in months (PRD §3.1)
ATG_TIGHTNESS_INTERVAL_MONTHS = 12
MANUAL_GAUGING_TIGHTNESS_INTERVAL_MONTHS = 60
LINE_TIGHTNESS_INTERVAL_MONTHS = 12
LLD_FUNCTION_INTERVAL_MONTHS = 12
CP_SURVEY_INTERVAL_MONTHS = 36
SPILL_OVERFILL_INTERVAL_MONTHS = 36

# Compliance posture (PRD §2.9)
POSTURE_BASE = 100
CRITICAL_WEIGHT = 25
MAJOR_WEIGHT = 15
MINOR_WEIGHT = 5
ESCALATED_EXTRA = 5
OPEN_RELEASE_WEIGHT = 10
LAPSED_OPERATOR_WEIGHT = 5
COMPLIANT_MIN = 85
DEFICIENT_MIN = 60

# Deficiency deadlines in days (PRD §3.5)
CRITICAL_DAYS = 7
MAJOR_DAYS = 30
MINOR_DAYS = 90

# Fund math (PRD §3.8)
OCCURRENCE_DEDUCTIBLE_CENTS = 1000000
AGGREGATE_YEAR_DEDUCTIBLE_CENTS = 2000000
COINSURANCE_RATE = 0.90
FUND_YEAR_CAP_CENTS = 100000000

# Release reporting (PRD §3.8)
REPORT_WINDOW_HOURS = 24

# Training validity in months (PRD §3.7)
VALIDITY_MONTHS = {"A": 36, "B": 36, "C": 12}

# Monthly close timing (PRD §3.9)
RECORD_DUE_DAY_OF_NEXT_MONTH = 10   # on-time through 23:59:59.999 on the 10th
CLOSE_AVAILABLE_DAY = 11            # close runnable from 00:00:00 on the 11th

# Service type -> required technician endorsement (PRD §3.3)
ENDORSEMENT_FOR_SERVICE = {
    "TANK_TIGHTNESS": "TIGHTNESS_TESTER",
    "LINE_TIGHTNESS": "TIGHTNESS_TESTER",
    "LLD_FUNCTION": "LLD_TESTER",
    "CP_SURVEY": "CP_TESTER",
    "SPILL_OVERFILL_INSPECTION": "INSPECTOR",
}
