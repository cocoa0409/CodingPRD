"""Domain thresholds — numeric constants from the PRD's fee, window, and
scoring formulas. Generic NON_EXISTENT_UUID comes from the framework.
"""

# Application filing fee (PRD §3.2)
FILING_FEE = {
    "TEAS_PLUS_PER_CLASS_CENTS": 25000,
    "TEAS_STANDARD_PER_CLASS_CENTS": 35000,
    "INTENT_SURCHARGE_PER_CLASS_CENTS": 10000,
}

# Maintenance fee (PRD §3.5)
MAINTENANCE_FEE = {
    "SECTION_8_PER_CLASS_CENTS": 22500,
    "SECTION_9_PER_CLASS_CENTS": 30000,
    "GRACE_SURCHARGE_PER_CLASS_CENTS": 10000,
}

# Madrid international fee (PRD §3.7)
MADRID_FEE = {
    "MADRID_BASE_CENTS": 65300,
    "MADRID_PER_COUNTRY_CENTS": 10000,
}

# Statutory windows in days / years (PRD §2.7)
WINDOWS = {
    "RESPONSE_PERIOD_DAYS": 90,
    "NONFINAL_GRACE_DAYS": 30,
    "FINAL_GRACE_DAYS": 0,
    "OPPOSITION_WINDOW_DAYS": 30,
    "ANSWER_PERIOD_DAYS": 40,
    "SOU_INITIAL_DAYS": 180,
    "SOU_MAX_DAYS": 1260,
    "DEPENDENCY_YEARS": 5,
}

# Maintenance windows in years / days (PRD §3.5)
MAINTENANCE_WINDOW = {
    "FIRST_WINDOW_YEARS": 6,
    "RENEWAL_PERIOD_YEARS": 10,
    "WINDOW_LEAD_YEARS": 1,
    "GRACE_WINDOW_DAYS": 180,
}

# Prosecution risk score weights (PRD §3.7)
RISK_SCORE = {
    "W_OPEN_OA": 15,
    "W_LATE_RESP": 10,
    "W_DEFAULT": 40,
    "W_GRACE_REG": 20,
    "SCORE_CEILING": 100,
}
