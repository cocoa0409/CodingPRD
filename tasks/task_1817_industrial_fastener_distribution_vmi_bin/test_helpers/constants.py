"""Domain thresholds — numeric constants named by the PRD calculations."""

# Order pricing (PRD §3.4)
QTY_TIER1_MIN = 100          # 2% discount at >= 100 pieces
QTY_TIER2_MIN = 500          # 5% discount at >= 500 pieces
TIER1_DISCOUNT_PCT = 2
TIER2_DISCOUNT_PCT = 5
CERT_FEE_CENTS = 1500        # flat certification handling fee on critical parts

# Sizing recommendation (PRD §3.2)
LOOKBACK_WEEKS = 4
SAFETY_FACTOR = 1.5
MAX_MULTIPLE = 3

# Kit packaging charge (PRD §3.6)
PER_BAG_CENTS = 250
PER_UNIT_CENTS = 3
PART_SURCHARGE_PCT = 4

# Station reservation buffer (PRD §3.6)
STATION_BUFFER_MINUTES = 15

# Logical clock default before any set call (PRD §2.4)
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Common schedule anchors used across tests
ROUTE_DATE = "2026-08-10T00:00:00Z"
WINDOW_START = "2026-08-10T08:00:00Z"
WINDOW_END = "2026-08-10T12:00:00Z"
CLOCK_INSIDE_WINDOW = "2026-08-10T09:00:00Z"
STATION_WINDOW_START = "2026-08-10T08:00:00Z"
STATION_WINDOW_END = "2026-08-10T09:00:00Z"
