"""Domain thresholds — numeric constants from the PRD's calculations
(buyer's premium, droit de suite royalty, minimum next bid).

All amounts are integer cents. Generic NON_EXISTENT_UUID comes from the
framework.
"""

# --- Droit de suite resale royalty (PRD §3.7) ---
ROYALTY_FLOOR_CENTS = 100000          # 1,000.00 — below this, no royalty row
ROYALTY_CAP_CENTS = 1250000           # 12,500.00 — absolute per-lot cap
ROYALTY_BAND_1_TOP_CENTS = 5000000    # 50,000.00
ROYALTY_BAND_2_TOP_CENTS = 20000000   # 200,000.00
ROYALTY_BAND_3_TOP_CENTS = 35000000   # 350,000.00
ROYALTY_BAND_4_TOP_CENTS = 50000000   # 500,000.00
ROYALTY_RATE_1_BPS = 400
ROYALTY_RATE_2_BPS = 300
ROYALTY_RATE_3_BPS = 100
ROYALTY_RATE_4_BPS = 50
ROYALTY_RATE_5_BPS = 25

# --- Minimum next bid increment bands (PRD §3.5) ---
STARTING_BID_FLOOR_CENTS = 5000       # 50.00 minimum opening bid
BID_BAND_1_TOP_CENTS = 100000         # 1,000.00
BID_BAND_2_TOP_CENTS = 500000         # 5,000.00
BID_BAND_3_TOP_CENTS = 2000000        # 20,000.00
BID_INCREMENT_1_CENTS = 5000          # 50.00
BID_INCREMENT_2_CENTS = 10000         # 100.00
BID_INCREMENT_3_CENTS = 25000         # 250.00
BID_INCREMENT_4_CENTS = 100000        # 1,000.00

# --- Consignment commission bounds (PRD §3.2) ---
MAX_SELLER_COMMISSION_BPS = 5000      # 50.00%

# --- Pagination (PRD §2.3) ---
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# Convenience defaults used across fixtures/tests.
TEST_DEFAULTS = {
    "BIG_CREDIT_LIMIT_CENTS": 500000000,
    "DEFAULT_COMMISSION_BPS": 1000,
}
