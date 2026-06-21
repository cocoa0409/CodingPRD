"""Domain thresholds — numeric constants from the PRD's calculations and rules.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Bid increment tiers (PRD §3.3) — increment measured on the price `p` in cents.
BID_INCREMENT = {
    "T1_EDGE_CENTS": 10000,   # < 10000 -> 100
    "T2_EDGE_CENTS": 50000,   # [10000, 50000) -> 500
    "T3_EDGE_CENTS": 100000,  # [50000, 100000) -> 1000; >= 100000 -> 2500
    "INC_T0_CENTS": 100,
    "INC_T1_CENTS": 500,
    "INC_T2_CENTS": 1000,
    "INC_T3_CENTS": 2500,
}

# Anti-sniping window (PRD §3.4).
SNIPE_TRIGGER_SECONDS = 300
SNIPE_EXTENSION_SECONDS = 300

# Offer negotiation (PRD §3.5).
OFFER_TTL_SECONDS = 86400      # 24h
OFFER_MAX_ROUNDS = 5

# Bid retraction lockout (PRD §3.3).
BID_RETRACT_LOCKOUT_SECONDS = 43200   # 12h

# Return / dispute windows (PRD §3.9, §3.10).
RETURN_WINDOW_SECONDS = 1209600       # 14d
DISPUTE_RESPONSE_SECONDS = 259200     # 72h

# Seller fee (PRD §3.7).
SELLER_FEE = {
    "FVF_T1_EDGE_CENTS": 25000,
    "FVF_T2_EDGE_CENTS": 75000,
    "FVF_BP_T1": 1255,   # 12.55%
    "FVF_BP_T2": 925,    # 9.25%
    "FVF_BP_T3": 255,    # 2.55%
    "INSERTION_FEE_CENTS": 30,
    "FVF_CAP_CENTS": 75000,
}

# Account standing gate (PRD §2.8).
FEE_SUSPEND_THRESHOLD_CENTS = 3000

# Pagination defaults (PRD §2.3).
PAGINATION = {"DEFAULT_LIMIT": 10, "MIN_LIMIT": 1, "MAX_LIMIT": 100, "DEFAULT_OFFSET": 0}
