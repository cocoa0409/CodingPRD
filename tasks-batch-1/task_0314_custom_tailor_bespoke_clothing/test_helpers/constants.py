"""Domain thresholds — numeric constants from the PRD's pricing and policy rules.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Option upcharge table (cents), frozen onto a line at creation (PRD §3.2).
UPCHARGE_TABLE = {
    "MONOGRAM": 1500,
    "CONTRAST_LINING": 4000,
    "WORKING_CUFFS": 6000,
    "PICK_STITCH": 3500,
    "EXTRA_TROUSER": 9000,
}

# Tiered yardage marginal multipliers (PRD §3.2).
YARDAGE = {
    "TIER1_MAX_M": 3.0,
    "TIER2_MAX_M": 6.0,
    "TIER1_MULT": 1.00,
    "TIER2_MULT": 0.90,
    "TIER3_MULT": 0.80,
}

# Pricing / deposit / rush policy.
RATES = {
    "RUSH_RATE": 0.30,
    "DEPOSIT_RATE": 0.50,
    "RUSH_DEPOSIT_FLOOR_CENTS": 20000,
    "OVERPAY_TOLERANCE_CENTS": 0,
}

# Remake policy (PRD §3.5).
REMAKE = {
    "MAX_REMAKES": 2,
    "REMAKE_BASE_CENTS": 5000,
    "REMAKE_STEP_CENTS": 3000,
}

# Customer remake-risk band boundaries (PRD §3.6), each inclusive.
RISK = {
    "WATCH_THRESHOLD": 0.34,
    "HIGH_THRESHOLD": 0.50,
}

# Group order policy (PRD §3.9).
GROUP = {
    "GROUP_MIN_MEMBERS": 3,
    "GROUP_TIER1_MIN": 4,
    "GROUP_TIER1_DISC": 0.05,
    "GROUP_TIER2_MIN": 8,
    "GROUP_TIER2_DISC": 0.10,
}

# Default fitting-room cleanup buffer (PRD §3.1).
DEFAULT_CLEANUP_BUFFER_MINUTES = 15

# A syntactically valid UUID that resolves to no entity (for not-found probes).
FAKE_UUID = "00000000-0000-4000-8000-000000000000"
