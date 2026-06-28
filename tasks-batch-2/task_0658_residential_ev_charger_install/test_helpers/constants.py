"""Domain thresholds — numeric constants from the PRD's calculation rules.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Panel-load (NEC) calculation constants (PRD §3.2)
PANEL = {
    "GENERAL_VA_PER_SQFT": 3,
    "SMALL_APPLIANCE_CIRCUIT_VA": 1500,
    "SMALL_APPLIANCE_CIRCUIT_COUNT": 2,
    "LAUNDRY_VA": 1500,
    "STD_FIRST_TIER_VA": 8000,
    "STD_REMAINDER_FACTOR": 0.40,
    "LOAD_STUDY_FACTOR": 1.25,
    "CONTINUOUS_FACTOR": 1.25,
    "DEFAULT_SERVICE_VOLTAGE": 240,
}

# Quote pricing constants (PRD §3.4)
QUOTE = {
    "DISC_TIER_HI_CENTS": 200000,
    "DISC_TIER_MID_CENTS": 100000,
    "DISC_PCT_HI": 0.10,
    "DISC_PCT_MID": 0.05,
    "PERMIT_HI_NET_CENTS": 150000,
    "PERMIT_MID_NET_CENTS": 90000,
    "PERMIT_HI_CENTS": 20000,
    "PERMIT_MID_CENTS": 15000,
    "PERMIT_LO_CENTS": 12000,
    "TAX_RATE": 0.0825,
}

# Incentive constants (PRD §3.8)
INCENTIVE = {
    "FED_RATE": 0.30,
    "FED_CAP_CENTS": 100000,
    "BASIC_BASE_CENTS": 25000,
    "PREMIUM_BASE_CENTS": 50000,
    "PANEL_UPGRADE_ADDER_CENTS": 30000,
    "STACK_CAP_PCT": 0.80,
}

# Circuit-to-panel sizing bands (PRD §2.10): panel amps -> max circuit amps
PANEL_CIRCUIT_BAND = {
    100: 40,
    150: 50,
    200: 60,
}

# Electrician defaults (PRD §3.1)
ELECTRICIAN_DEFAULT_MAX_DAILY_JOBS = 2
