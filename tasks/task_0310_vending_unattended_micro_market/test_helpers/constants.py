"""Domain thresholds — numeric constants from the PRD calculations (Section 3).

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Tiered commission marginal bands (PRD Section 3.7).
COMMISSION_BANDS = {
    "BAND1_CAP": 500000,     # portion [0, 500000) at BAND1_RATE
    "BAND2_CAP": 1500000,    # portion [500000, 1500000) at BAND2_RATE
    "BAND1_RATE": 0.08,
    "BAND2_RATE": 0.12,
    "BAND3_RATE": 0.15,      # portion at/above 1500000
}

# Shrink chargeback: host bears one half of shrink value (PRD Section 3.7).
HOST_SHRINK_SHARE = 0.50

# Defaults declared by the PRD for optional inputs (Sections 3.1-3.2).
DEFAULTS = {
    "FLAT_COMMISSION_PCT": 0.10,
    "MONTHLY_GUARANTEE_CENTS": 0,
    "CASH_CAPACITY_CENTS": 50000,
    "CASH_ALERT_THRESHOLD_PCT": 0.80,
    "PAR_FILL_THRESHOLD_PCT": 0.25,
}

# A syntactically valid UUID that is never minted by the server.
MISSING_UUID = "00000000-0000-4000-8000-000000000000"
