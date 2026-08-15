"""Domain thresholds — numeric constants named in the PRD."""

# The writer pool is one half of the net: 5000 of 10000 basis points.
WRITER_POOL_BP = 5000
BASIS_POINTS_TOTAL = 10000

# Sub-publisher retention is never more than half the gross.
MAX_RETENTION_BP = 5000

# Minimum payable balance (in cents) for inclusion in a distribution run;
# the boundary is inclusive.
MIN_PAYOUT_CENTS = 2500

# Termination-window projection constants (calendar years).
WINDOW_OPEN_YEARS = 35
WINDOW_CLOSE_YEARS = 40
NOTICE_EARLIEST_YEARS = 10
NOTICE_LATEST_YEARS = 2

# The logical clock reads exactly this instant before any operator sets it.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Default recoupment rate on a new advance when none is supplied.
DEFAULT_RECOUP_RATE_BP = 10000
