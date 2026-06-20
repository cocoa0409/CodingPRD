"""Domain thresholds — numeric constants from PRD calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Benefit trigger 2-of-6 decision (PRD 3.3)
ADL_TRIGGER_COUNT = 2
VALID_ADLS = ["BATHING", "DRESSING", "TOILETING", "TRANSFERRING", "CONTINENCE", "EATING"]

# Inflation growth rates (PRD 3.2)
INFLATION_RATES = {
    "NONE": 0.0,
    "COMPOUND_3PCT": 0.03,
    "COMPOUND_5PCT": 0.05,
}

# Care setting -> provider type compatibility (PRD 3.4, one-to-one)
CARE_SETTING_TO_PROVIDER_TYPE = {
    "NURSING_HOME": "NURSING_HOME",
    "ASSISTED_LIVING": "ASSISTED_LIVING",
    "HOME_HEALTH": "HOME_HEALTH_AGENCY",
    "ADULT_DAY": "ADULT_DAY_CARE",
    "INFORMAL": "INFORMAL_CAREGIVER",
}

# Sensible test defaults for a standard policy.
TEST_DEFAULTS = {
    "DAILY_BENEFIT_MAX_CENTS": 20000,
    "MONTHLY_BENEFIT_MAX_CENTS": 600000,
    "INITIAL_POOL_CENTS": 10000000,
    "BASE_PREMIUM_CENTS": 12000,
    "DUE_DATE": "2026-01-31",
    "GRACE_DEADLINE": "2026-04-06",
}
