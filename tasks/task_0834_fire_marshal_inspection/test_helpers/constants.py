"""Domain thresholds — numeric constants from the PRD's calculations and rules."""

# --- Permit fee (PRD §3.3) ---
BASE_PERMIT_FEE_CENTS = {
    "CONSTRUCTION": 20000,
    "TENANT_IMPROVEMENT": 10000,
    "HAZMAT": 30000,
    "TANK": 25000,
}
VALUATION_RATE = 0.005
STATE_SURCHARGE_RATE = 0.001
TECH_FEE_RATE = 0.0004
RESUBMIT_SURCHARGE_CENTS = 5000

# --- Occupant load (PRD §3.1) ---
OCCUPANT_LOAD_FACTOR = {
    "ASSEMBLY": 7,
    "BUSINESS": 150,
    "EDUCATIONAL": 20,
    "FACTORY": 100,
    "HIGH_HAZARD": 100,
    "INSTITUTIONAL": 240,
    "MERCANTILE": 60,
    "RESIDENTIAL": 200,
    "STORAGE": 500,
    "UTILITY": 300,
}
NET_AREA_RATIO = 0.85

# --- Required exits step function (PRD §3.1) ---
EXIT_T1 = 50
EXIT_T2 = 500
EXIT_T3 = 1000

# --- Required fire flow (PRD §3.1) ---
FLOW_COEFF = 0.09
CONSTRUCTION_FACTOR = {
    "TYPE_I": 0.8,
    "TYPE_II": 0.8,
    "TYPE_III": 1.0,
    "TYPE_IV": 1.0,
    "TYPE_V": 1.5,
}
OCCUPANCY_HAZARD_MULT = {
    "HIGH_HAZARD": 1.5,
    "STORAGE": 1.25,
    "FACTORY": 1.25,
    "ASSEMBLY": 1.0,
    "INSTITUTIONAL": 1.0,
    "EDUCATIONAL": 1.0,
    "BUSINESS": 0.75,
    "MERCANTILE": 0.75,
    "RESIDENTIAL": 0.75,
    "UTILITY": 0.75,
}
FLOW_MIN_GPM = 500
FLOW_MAX_GPM = 8000
FLOW_STEP = 250

# --- Flow test projection (PRD §3.2) ---
RESIDUAL_TARGET_PSI = 20
HW_EXPONENT = 0.54

# --- Abatement deadlines (PRD §3.7) ---
ABATEMENT_GRACE_DAYS = {
    "IMMINENT_HAZARD": 3,
    "MAJOR": 30,
    "MINOR": 90,
}

# --- Temporal buffers / windows ---
INSPECTION_BUFFER_DAYS = 14
FLOW_TEST_WINDOW_DAYS = 365
PERMIT_EXPIRY_DAYS = 365

# --- Logical clock ---
CLOCK_STARTUP_DEFAULT = "2026-03-01T00:00:00Z"
