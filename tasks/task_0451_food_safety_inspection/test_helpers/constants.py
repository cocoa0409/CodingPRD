"""Domain thresholds — numeric constants from the PRD's calculation and scheduling rules.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Risk-category seating bands and routine intervals (PRD §3.2).
RISK = {
    "CAT2_SEATS": 50,
    "CAT3_SEATS": 150,
    "INTERVAL_CAT1": 365,
    "INTERVAL_CAT2": 180,
    "INTERVAL_CAT3": 90,
}

# Inspection scoring base (PRD §2.9 / §3.5).
SCORING = {
    "BASE_SCORE": 100,
}

# Grade / placard cut points and closure overrides (PRD §3.6).
GRADE = {
    "A_CUT": 90,
    "B_CUT": 80,
    "CRITICAL_CLOSE_COUNT": 3,
    "HARD_CLOSE_SCORE": 60,
}

# Complaint severity weights and bands (PRD §3.9).
COMPLAINT = {
    "TYPE_FOODBORNE_ILLNESS": 40,
    "TYPE_SANITATION": 15,
    "TYPE_OTHER": 5,
    "ILL_CAP": 10,
    "ILL_POINT": 4,
    "RISK_CAT1": 0,
    "RISK_CAT2": 5,
    "RISK_CAT3": 10,
    "URGENT_CUT": 60,
    "PRIORITY_CUT": 30,
}

# Plan-review fee tiers (PRD §3.2).
PLAN_FEE = {
    "BASE_FEE_CENTS": 20000,
    "TIER1_CAP_SQFT": 500,
    "TIER2_CAP_SQFT": 1000,   # marginal sqft from 501..1500
    "T2_RATE": 50,
    "T3_RATE": 80,
    "EQUIP_FEE_CENTS": 1500,
}

# Permit fee scaled by risk category (PRD §3.3).
PERMIT_FEE = {
    "FEE_CAT1": 30000,
    "FEE_CAT2": 60000,
    "FEE_CAT3": 120000,
}

# Penalty assessment (PRD §3.10).
PENALTY = {
    "REDUCED_RATIO": 0.5,
}

# Logical-clock scheduling constants (PRD §3.3 / §3.7 / §3.8).
SCHEDULE = {
    "PERMIT_TERM_DAYS": 365,
    "REINSPECTION_GRACE_DAYS": 14,
}

# Default payload values used by factories.
TEST_DEFAULTS = {
    "ESTABLISHMENT_NAME": "Diner E1",
    "ESTABLISHMENT_ADDRESS": "1 Main St",
    "SEATING_CAPACITY": 40,
    "PLAN_SQFT": 400,
    "PLAN_EQUIP": 5,
    "INSPECTOR_NAME": "Ivy One",
    "BADGE_NUMBER": "B-001",
}
