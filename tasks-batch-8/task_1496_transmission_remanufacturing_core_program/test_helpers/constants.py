"""Domain thresholds — numeric constants named in the PRD (§2.5, §3.1-§3.8)."""

# Logical clock (PRD §2.5): startup default before any adjustment.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Core deposit invoice (PRD §3.5): provisional estimate factor.
PROVISIONAL_CREDIT_FACTOR = 0.8

# Core grading (PRD §3.6): finding weights, grade bands, lateness tiers.
FINDING_WEIGHTS = {
    "TORQUE_CONVERTER_MISSING": 20,
    "VALVE_BODY_MISSING": 25,
    "SENSOR_HARNESS_MISSING": 10,
    "BELL_HOUSING_DAMAGED": 15,
    "PAN_MISSING": 5,
}
GRADE_A_MAX = 5
GRADE_B_MAX = 15
GRADE_C_MAX = 30
GRADE_MULTIPLIER = {"A": 1.0, "B": 0.75, "C": 0.5}
ON_TIME_DAYS = 30
LATE_CUTOFF_DAYS = 45
LATE_CREDIT_FACTOR = 0.75

# Dyno scoring (PRD §3.4).
PENALTY_PER_KPA = 2.0
PASS_MIN = 90.0
MARGINAL_MIN = 80.0
MAX_DYNO_ATTEMPTS = 3

# Kit reservation (PRD §3.2).
ADAPTED_SURCHARGE_MINUTES = 30

# Calibration (PRD §3.3).
CAL_MAX_AGE_HOURS = 72

# Dock scheduling (PRD §3.6).
DOCK_TURNAROUND_BUFFER_MINUTES = 30

# Defective-return routing (PRD §3.8).
ROUTING_VALUE_THRESHOLD_CENTS = 50000

# Model defaults (PRD §3.1).
DEFAULT_WARRANTY_DAYS = 365

# Standard MIN-spec model values used across fixtures.
MIN_MODEL = {
    "model_code": "MIN-6L80",
    "year_start": 2014,
    "year_end": 2019,
    "make": "GM",
    "model": "Silverado",
    "core_deposit_cents": 50000,
    "flat_rate_hours": 6.0,
    "labor_cap_cents": 90000,
    "dyno_targets": [
        {"gear": 1, "target_pressure_kpa": 200},
        {"gear": 2, "target_pressure_kpa": 220},
        {"gear": 3, "target_pressure_kpa": 240},
        {"gear": 4, "target_pressure_kpa": 260},
    ],
    "required_parts": [],
}

# Pressure vector exactly matching the MIN-model dyno targets (score 100, PASS).
PASS_PRESSURES = [200, 220, 240, 260]
# 15 kPa low on gear 1: penalty 30.00 -> score 70.00 (FAIL).
FAIL_PRESSURES = [185, 220, 240, 260]
# 10 kPa low on gear 1: penalty 20.00 -> score 80.00 (MARGINAL).
MARGINAL_PRESSURES = [190, 220, 240, 260]
