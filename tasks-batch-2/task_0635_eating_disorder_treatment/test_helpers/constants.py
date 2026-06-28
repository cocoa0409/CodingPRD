"""Domain thresholds — numeric constants from the PRD's calculations."""

# recommended_level_of_care (composite score thresholds, inclusive lower bound)
LOC_THRESHOLDS = {
    "T_RESIDENTIAL": 70,
    "T_PHP": 50,
    "T_IOP": 30,
}
LOC_WEIGHTS = {
    "W_MEDICAL": 0.40,
    "W_BEHAVIORAL": 0.30,
    "W_PSYCHIATRIC": 0.20,
    "W_MOTIVATION": -0.10,
}

# nutritional_risk_score
BMI_SEVERE_BONUS = 15  # bmi < 16
BMI_MODERATE_BONUS = 7  # 16 <= bmi < 18.5
MEDICAL_HOLD_RISK_BUMP = 10
MEAL_CREDIT_FACTOR = 40

# medical_stability_posture (inclusive lower bound)
POSTURE_THRESHOLDS = {
    "T_UNSTABLE": 75,
    "T_GUARDED": 50,
}

# step_down_readiness_score
STEP_DOWN_THRESHOLD = 75
MEAL_COMPLIANCE_FLOOR = 0.80
MIN_MEALS_FOR_STEP_DOWN = 3
STEP_DOWN_WEIGHTS = {
    "W_GOALS": 0.45,
    "W_MEALS": 0.35,
    "W_STABILITY": 0.20,
}

# authorized_days_balance
SECONDS_PER_DAY = 86400

# Logical clock default at server startup
CLOCK_DEFAULT_ISO = "2026-01-01T00:00:00Z"
