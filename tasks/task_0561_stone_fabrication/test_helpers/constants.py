"""Domain thresholds — numeric constants from the PRD's pricing and inventory rules."""

# Per-square-foot material rate in cents, by grade (PRD §3.1 / §3.3).
MATERIAL_RATE_CENTS = {"STANDARD": 4500, "PREMIUM": 6500, "EXOTIC": 9500}

# Per-linear-foot edge rate in cents, by profile (PRD §3.1 / §3.3).
EDGE_RATE_CENTS = {"EASED": 0, "BEVELED": 800, "BULLNOSE": 1200, "OGEE": 2000}

# Per-cutout charge in cents, by type (PRD §3.1 / §3.3).
CUTOUT_CHARGE_CENTS = {"SINK": 15000, "FAUCET": 3500, "COOKTOP": 12000}

# Minimum job floor in cents (PRD §3.1).
MIN_JOB_CENTS = 80000

# Tax rate applied per line on the final invoice (PRD §3.3).
TAX_RATE = 0.0875

# Deposit percentage of the quoted total (PRD §3.2).
DEPOSIT_PCT = 0.50

# Slab planning-yield waste factor and kerf allowance (PRD §3.4 / §3.5).
STD_WASTE_FACTOR = 0.15
KERF_SQFT_PER_PIECE = 0.10

# Crew scheduling travel buffer, in days (PRD §3.6).
TRAVEL_BUFFER_DAYS = 1

# Warranty window length, in days (PRD §3.8).
WARRANTY_DAYS = 365

# Logical-clock startup default (PRD §2.10).
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"
