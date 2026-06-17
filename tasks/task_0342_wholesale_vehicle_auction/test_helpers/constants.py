"""Domain thresholds — numeric constants from the PRD's monetary calculations."""

# Bid increment ladder (PRD §3.5). Band boundaries: lower exclusive, upper inclusive.
BID_INCREMENT = {
    "BAND1_MAX_CENTS": 500000,   # < $5,000
    "BAND2_MAX_CENTS": 1000000,  # < $10,000
    "INCR_BAND1": 10000,         # $100
    "INCR_BAND2": 25000,         # $250
    "INCR_BAND3": 50000,         # $500
}

# Buyer fee schedules (PRD §3.7). Flat-per-band, never marginal.
BUYER_FEE = {
    "STANDARD_FLOOR_FEE": 12500,     # S < $2,000
    "STANDARD_MID_PCT": 0.06,        # $2,000..$9,999.99
    "STANDARD_HIGH_PCT": 0.04,       # >= $10,000
    "STANDARD_HIGH_ADDON": 20000,
    "PREMIUM_FLOOR_FEE": 17500,
    "PREMIUM_MID_PCT": 0.08,
    "PREMIUM_HIGH_PCT": 0.05,
    "PREMIUM_HIGH_ADDON": 25000,
    "ONLINE_SURCHARGE_PCT": 0.10,
    "MID_BAND_FLOOR_CENTS": 200000,
    "HIGH_BAND_FLOOR_CENTS": 1000000,
}

# Seller net proceeds (PRD §3.8).
SELLER_PROCEEDS = {
    "SELLER_FEE_CAP_CENTS": 150000,
    "ASSURANCE_FEE_CENTS": 5000,
    "DEFAULT_SELLER_FEE_PCT": 0.02,
}

# Arbitration credit (PRD §3.10).
ARBITRATION = {
    "MAX_CREDIT_PCT": 0.30,
}

# Carrier turnaround buffer default (PRD §3.11).
CARRIER_DEFAULT_BUFFER_MINUTES = 30

# Condition report grade threshold for as_is (PRD §3.3).
AS_IS_GRADE_THRESHOLD = 3.0

# Pagination (PRD §2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Common large credit line used in setups so credit never blocks bidding.
DEFAULT_CREDIT_LIMIT_CENTS = 5_000_000
