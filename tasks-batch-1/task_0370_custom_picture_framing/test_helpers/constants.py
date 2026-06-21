"""Domain thresholds — numeric constants from PRD calculations."""

# Per-line pricing (PRD Section 3.3)
LINE_COST = {
    "MAT_RATE_PER_SQFT": 6.00,
    "GLASS_RATE": {"REGULAR": 4.00, "CONSERVATION": 9.00, "MUSEUM": 18.00},
    "UI_TIER1": 80,
    "OVERSIZE_TIER1": 40.00,
    "UI_TIER2": 120,
    "OVERSIZE_TIER2": 95.00,
    "MOUNT_UPCHARGE": {"NONE": 0.00, "PLAIN": 15.00, "DRY_MOUNT": 35.00, "CONSERVATION_HINGE": 55.00},
    "CONSERVATION_MULT": 1.20,
    "LABOR_PER_LINE": 45.00,
}

# Quote estimate / final invoice (PRD Sections 3.4 / 3.7)
RUSH_PCT = 0.15

# Loyalty discount fractions (PRD Section 3.1)
LOYALTY_DISCOUNT = {"STANDARD": 0.00, "PREFERRED": 0.10, "TRADE": 0.15}

# Deposit (PRD Section 3.4)
FRAGILE_DEPOSIT_FLOOR_PCT = 0.50
MIN_DEPOSIT = 25.00

# Turnaround (PRD Section 3.4)
BASE_TURNAROUND_DAYS = 14
FRAGILE_EXTRA_DAYS = 5

# Forward no-show risk (PRD Section 3.1)
OPEN_WEIGHT = 5
READY_UNPAID_WEIGHT = 15
RISK_CEILING = 100

# Settled reputation (PRD Section 3.1)
SEED_BASE = 50
ONTIME_DELTA = 10
ABANDON_DELTA = 20
REP_FLOOR = 0
REP_CEILING = 100

# deposit_pct closed range (PRD Section 3.2)
DEPOSIT_PCT_MIN = 0.10
DEPOSIT_PCT_MAX = 1.00

# A syntactically-valid UUID guaranteed not to resolve to any entity.
MISSING_UUID = "00000000-0000-4000-8000-000000000000"
