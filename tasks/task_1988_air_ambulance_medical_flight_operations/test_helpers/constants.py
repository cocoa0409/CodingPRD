"""Domain thresholds and charge constants from the PRD (§2.4, §2.5, §3.1, §3.4, §3.8, §3.9)."""

# Logical clock startup default (PRD §2.4).
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

# Acuity scoring weights and breaks (PRD §3.2).
TRIAGE_W = {"cardio": 0.30, "resp": 0.30, "neuro": 0.20, "interv": 0.20}
ACCEPTANCE_W = {"cardio": 0.25, "resp": 0.35, "neuro": 0.25, "interv": 0.15}
DETERIORATION_BONUS = 2.0
DETERIORATION_WINDOW_MIN = 120
TIER_CCT_MIN = 7.0
TIER_ALS_MIN = 4.0

# Weather minimums (PRD §3.4).
BASE_CEIL = {
    ("ROTOR_WING", "DAY"): 500,
    ("ROTOR_WING", "NIGHT"): 800,
    ("FIXED_WING", "DAY"): 800,
    ("FIXED_WING", "NIGHT"): 1200,
}
BASE_VIS = {
    ("ROTOR_WING", "DAY"): 1.0,
    ("ROTOR_WING", "NIGHT"): 3.0,
    ("FIXED_WING", "DAY"): 2.0,
    ("FIXED_WING", "NIGHT"): 3.0,
}
MOUNTAIN_CEIL_BONUS = 500
XWIND_MAX = {"ROTOR_WING": 25, "FIXED_WING": 30}
MARGINAL_XWIND_PAD = 5
MARGINAL_CEIL_FACTOR = 1.2
MARGINAL_VIS_PAD = 0.5
ASSESSMENT_TTL_MIN = 60

# Duty / rest governance (PRD §2.9, §3.1).
MAX_DUTY_MIN = 840
REST_MIN_MIN = 600
ROLLING_WINDOW_H = 24

# Invoice charge constants (PRD §3.8), integer cents.
BASE_LIFTOFF = {"ROTOR_WING": 1_800_000, "FIXED_WING": 950_000}
PER_MILE = {"ROTOR_WING": 16_000, "FIXED_WING": 4_500}
FUEL_PCT = 7
ACUITY_FEE = {"BLS": 0, "ALS": 120_000, "CCT": 350_000}
LOGISTICS_THRESHOLD = 2_500_000
LOGISTICS_PCT = 4
GROUND_LEG_FLAT = 45_000
PROVISIONAL_MILE_FACTOR = 1.15

# Revenue-cycle windows (PRD §3.8).
TIMELY_FILING_DAYS = 90
APPEAL_CAP = 2

# Membership reinstatement window (PRD §3.2).
REINSTATE_WINDOW_DAYS = 30

# PCR submission window (PRD §3.9).
PCR_WINDOW_HOURS = 24

# QA remediation threshold and window (PRD §3.9).
REMEDIATION_THRESHOLD = 15
QA_WINDOW_DAYS = 90

# Repatriation document validity (PRD §3.7).
FIT_TO_FLY_MAX_AGE_HOURS = 72
