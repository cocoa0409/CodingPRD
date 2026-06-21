"""Domain thresholds — numeric constants from the PRD calculations and gates.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# SEP deadline (PRD §3.10): birth + 30 calendar days; weekend roll target time.
SEP_WINDOW_DAYS = 30
WEEKEND_ROLL_TARGET_TIME = "23:59:59.999Z"

# Discharge-readiness scoring (PRD §3.8).
READINESS_PASS_THRESHOLD = 70
WEIGHT_TIER_HIGH_G = 2500      # 40 pts
WEIGHT_TIER_MID_G = 2000       # 25 pts
WEIGHT_TIER_LOW_G = 1800       # 10 pts
WEIGHT_PTS_HIGH = 40
WEIGHT_PTS_MID = 25
WEIGHT_PTS_LOW = 10
FEEDING_PTS = 30
NICU_CLEAR_PTS = 20
FILING_PTS = 10
READINESS_SCORE_CAP = 100

# Discharge-bag valuation multipliers (PRD §3.6).
CATEGORY_MULTIPLIERS = {
    "FORMULA": 1.00,
    "DIAPERS": 1.00,
    "CARSEAT_VOUCHER": 1.00,
    "MEDICATION": 1.05,
    "EDUCATION": 0.00,
}
MED_HANDLING_MULTIPLIER = 1.05
EDUCATION_MULTIPLIER = 0.00

# Government-filing deadlines (PRD §3.7).
BIRTH_CERT_DAYS = 5
SSN_DAYS = 365

# Follow-up task SLA windows in hours from discharged_at (PRD §3.9).
FOLLOWUP_SLA_HOURS = {
    "WEIGHT_CHECK": 48,
    "JAUNDICE_CHECK": 72,
    "FEEDING_CHECK": 120,
    "SAFETY_CALL": 168,
}

# NICU clinical-criteria gate (PRD §3.3).
NICU_GESTATION_MIN_WEEKS = 35  # >= 35 is clear
NICU_APGAR_MIN = 7             # >= 7 is clear
NICU_WEIGHT_MIN_G = 1800       # >= 1800 is clear

# Lactation consult buffer (PRD §3.5): closed +/- 240 minutes.
CONSULT_BUFFER_MINUTES = 240

# Admit window (PRD §3.1): [due_date - 21d, due_date + 21d] inclusive.
ADMIT_WINDOW_DAYS = 21

# Follow-up escalation (PRD §3.9): 3rd attempt escalates.
FOLLOWUP_ESCALATE_AT_ATTEMPT = 3
