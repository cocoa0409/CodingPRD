"""Domain thresholds and shared test values (PRD money/rate rules).

All money is integer micros (1 USD = 1,000,000 micros); all rates are
integer basis points (10,000 bps = 100%). Division-to-integer results are
rounded half-up, and rounded components are summed (never the reverse).
"""

# Logical clock (PRD: before any operator sets it, the clock reads exactly
# 2026-08-01T00:00:00Z).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Standard deal flight covering the default clock.
FLIGHT_START = "2026-08-01T00:00:00Z"
FLIGHT_END = "2026-12-31T00:00:00Z"

# Standard batch window covering the default clock's UTC date.
BATCH_PERIOD_START = "2026-08-01"
BATCH_PERIOD_END = "2026-09-01"

# Rate / fee constants (PRD auction pipeline).
NEUTRAL_MULTIPLIER_BPS = 10000
SECOND_PRICE_STEP_MICROS = 1000          # tenth-of-a-cent step above runner-up
TIER1_CAP_MICROS = 5_000_000             # first slab: [0, 5M] at 1500 bps
TIER2_CAP_MICROS = 20_000_000            # second slab: (5M, 20M] at 1000 bps
TIER1_BPS = 1500
TIER2_BPS = 1000
TIER3_BPS = 500                          # above 20M
DSP_FEE_BPS = 1000                       # 10% markup billed to the DSP
DISCREPANCY_THRESHOLD_PCT = 2.000        # auto-flag when strictly greater
MAX_CHAIN_FEE_BPS = 9000
MAX_CHAIN_HOPS = 10

# Capacity defaults.
DEFAULT_MAX_QPS = 100
DEFAULT_DAILY_CAP_MICROS = 100_000_000

# A canonical fill: bid 1,000,000 micros CPM x 1000 impressions on a deal
# whose pinned floor is <= 1,000,000 with no supply chain.
#   gross   = 1,000,000
#   fee     = 150,000   (slab 1 only: 15% of 1,000,000)
#   net     = 850,000
#   dsp_fee = 100,000   (10% of gross)
#   billed  = 1,100,000
STANDARD_BID_CPM_MICROS = 1_000_000
STANDARD_IMPRESSIONS = 1000
STANDARD_GROSS_MICROS = 1_000_000
STANDARD_EXCHANGE_FEE_MICROS = 150_000
STANDARD_NET_MICROS = 850_000
STANDARD_DSP_FEE_MICROS = 100_000
STANDARD_DSP_BILLED_MICROS = 1_100_000

# Operator identities (opaque roles; persisted ids where the PRD uses them).
FINANCE_USER_ID = "fin-1"
SECOND_ADMIN_USER_ID = "admin-2"
