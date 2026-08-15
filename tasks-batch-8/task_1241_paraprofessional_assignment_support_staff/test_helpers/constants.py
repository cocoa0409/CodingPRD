"""Domain thresholds and numeric constants (PRD §3.1, §3.4).

All money values are integer cents; durations are integer minutes (PRD §2.6).
"""

THRESHOLDS = {
    # Default weekly scheduled minutes at/above which a para is benefit-eligible (PRD §3.1).
    "BENEFIT_THRESHOLD_MINUTES": 1800,
    # Default wage multiplier applied while benefit-eligible (PRD §3.1).
    "BENEFIT_SURCHARGE_PCT": 0.20,
    # Default required gap between same-day assignments in different buildings (PRD §3.1).
    "TRAVEL_BUFFER_MINUTES": 30,
    # Startup value of the logical clock (PRD §2.4).
    "DEFAULT_CLOCK_ISO": "2026-05-01T00:00:00Z",
}

# Qualification differentials, cents/hour added to base wage (PRD §3.4).
QUALIFICATION_DIFFERENTIAL_CENTS = {
    "NONE": 0,
    "BEHAVIOR_SUPPORT": 150,
    "MEDICAL_DELEGATION": 200,
    "SIGN_LANGUAGE": 250,
}

# One-to-one stipend, cents/hour added when service level is ONE_TO_ONE (PRD §3.4).
SERVICE_STIPEND_ONE_TO_ONE_CENTS = 100

TEST_DEFAULTS = {
    "PLAN_NAME": "FY27 SPED",
    "SCHOOL_YEAR": "2026-27",
    "TOTAL_BUDGET_CENTS": 100_000_000,
    "BUILDING_NAME": "Lincoln Elementary",
    "BUILDING_CODE": "LIN",
    "HARDSHIP_FACTOR": 1.0,
    "PARA_NAME": "Pat Para",
    "PARA_WAGE_CENTS": 2000,
    "PARA_CAP_MINUTES": 2400,
    "HIRE_DATE": "2025-08-15",
    "STUDENT_REF": "STU-001",
    "IEP_MINUTES": 1500,
    "START_DATE": "2026-05-04",
    "END_DATE": "2026-06-30",
    "WEEKDAYS": ["MON", "TUE", "WED", "THU", "FRI"],
    "DAY_START_MINUTE": 480,
    "DAY_END_MINUTE": 780,
}
