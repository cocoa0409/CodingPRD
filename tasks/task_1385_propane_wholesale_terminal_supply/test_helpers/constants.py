"""Domain thresholds — numeric constants named in the PRD.

Money constants are integer millicents per gallon (one millicent is
one-thousandth of a cent), matching the PRD's field units.
"""

# PRD section 3.5 pricing premia / surcharges
OVERAGE_PREMIUM_MC = 25_000          # "an overage premium of 25 cents per gallon"
SPOT_PREMIUM_MC = 40_000             # "a spot premium of 40 cents per gallon"
CREDIT_WATCH_SURCHARGE_MC = 15_000   # "a credit-watch surcharge of 15 cents per gallon"
WINTER_SURCHARGE_MC = 30_000         # "a winter surcharge of 30 cents per gallon"

# PRD section 3.6 dispatch constants
LOAD_SERVICE_MINUTES = 90            # "90 minutes of rack service time"
DEADHEAD_BUFFER_MINUTES = 60         # "60 minutes before/after" buffered window

# PRD section 3.4 order volume floor
MIN_ORDER_GAL = 1000                 # "a `requested_gal` of at least 1000 gallons"

# PRD section 2.5 logical clock startup default
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# PRD section 3.5: index basis for all INDEX and SPOT pricing
INDEX_BASIS = "MT_BELVIEU"

TEST_DEFAULTS = {
    "TERMINAL_STORAGE_GAL": 1_000_000,
    "RESERVE_FLOOR_GAL": 50_000,
    "WINTER_RESERVE_FLOOR_GAL": 150_000,
    "RACK_BAY_COUNT": 2,
    "STOCK_GAL": 400_000,
    "SUPPLY_CONTRACTED_GAL": 600_000,
    "RECEIPT_WINDOW_START": "2026-07-01",
    "RECEIPT_WINDOW_END": "2026-09-30",
    "SHIPMENT_ARRIVAL_DATE": "2026-08-05",
    "ZONE_ONE_WAY_MINUTES": 120,
    "ZONE_FREIGHT_MC_PER_GAL": 8_000,
    "ZONE_MIN_FREIGHT_CENTS": 150_000,
    "TRUCK_CAPACITY_GAL": 11_000,
    "TRUCK_WEEKLY_LIMIT_MINUTES": 3_600,
    "DEALER_CREDIT_LIMIT_CENTS": 100_000_000,
    "FIXED_PRICE_MC_PER_GAL": 90_000,
    "CONTRACT_COMMITTED_GAL": 100_000,
    "CONTRACT_WINDOW_START": "2026-08-01",
    "CONTRACT_WINDOW_END": "2027-03-31",
    "BASE_INDEX_MC_PER_GAL": 95_000,
    "BASE_INDEX_EFFECTIVE_DATE": "2026-08-01",
}
