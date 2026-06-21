"""Domain thresholds — numeric constants from the PRD fee, tolerance, and
risk-score rules (§3.7, §3.5, §3.3, §3.8). Generic NON_EXISTENT_UUID comes
from the framework.
"""

# Survey-type base fee tariff in cents (PRD §3.7).
BASE_FEE_BY_TYPE = {
    "BOUNDARY": 120000,
    "TOPO": 180000,
    "ALTA": 350000,
    "ELEVATION": 90000,
}

# Tiered per-acre field-fee bands (PRD §3.7): first 5 acres @ 8000, next 15 @ 5000,
# remainder @ 3000. Expressed as (band_width_acres or None for unbounded, rate_cents_per_acre).
ACRE_TIERS = [
    (5, 8000),       # first 5 acres
    (15, 5000),      # next 15 acres (above 5, up to 20)
    (None, 3000),    # every acre beyond 20
]

RUSH_PCT = 0.30      # rush surcharge percentage (PRD §3.7)
TAX_PCT = 0.0825     # invoice tax percentage (PRD §3.7)

# Re-seal surcharge by reason in cents (PRD §3.7).
RESEAL_FEE_BY_REASON = {
    "CLIENT_CHANGE": 40000,
    "DEED_DISCREPANCY": 25000,
    "FIELD_ERROR": 0,
}

# Seal closure tolerance: inclusive ceiling on DataSet.closure_error_ppm (PRD §3.5).
MAX_SEALABLE_CLOSURE_PPM = 100

# Instrument reservation turnaround buffer in minutes, applied on each side (PRD §3.3).
TURNAROUND_MINUTES = 60

# Crew scheduling-risk score constants (PRD §3.8).
OPEN_CAP = 5
EXPIRY_WARN_DAYS = 30
W_LOAD = 0.6
W_LICENSE = 0.4

# A syntactically valid UUID guaranteed not to address any created resource.
ABSENT_UUID = "00000000-0000-4000-8000-000000000000"
