"""Domain thresholds and constants named by the PRD."""

# Money / tax (PRD section 3.7)
TAX_THRESHOLD_CENTS = 60000          # prize value >= this is tax_reportable (inclusive)
BACKUP_WITHHOLDING_RATE = 0.24       # withheld fraction when no W-9 at disburse

# Score weights (PRD section 3.5)
W_CRAFTSMANSHIP = 0.5
W_ACCURACY = 0.3
W_PRESENTATION = 0.2
TRIM_MIN_PANEL = 3                   # TRIMMED_MEAN needs at least this many locked sheets

# Purse split shares (PRD section 3.1)
RANK1_SHARE = 0.50
RANK2_SHARE = 0.30

# Eligibility (PRD section 3.3)
JUNIOR_AGE_LIMIT = 16

# Green room (PRD section 3.9)
GREEN_ROOM_CAPACITY = 4
ACCESSIBLE_ROOMS = ["EAST"]

# Banned prop types (PRD section 3.3)
BANNED_PROP_TYPES = ["LIVE_STEEL", "FIREARM", "PYROTECHNICS"]

# Defaults (PRD sections 3.1-3.3)
DEFAULT_MAX_ENTRIES_PER_CONTESTANT = 2

# Logical clock (PRD section 2.7)
DEFAULT_LOGICAL_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Standard contest window used across scenarios
CONTEST_START = "2026-08-15T09:00:00Z"
CONTEST_END = "2026-08-15T22:00:00Z"

# Standard pre-judging slot windows inside the contest window
SLOT_START = "2026-08-15T10:00:00Z"
SLOT_END = "2026-08-15T11:00:00Z"
SLOT_START_2 = "2026-08-15T11:00:00Z"
SLOT_END_2 = "2026-08-15T12:00:00Z"

# Standard green-room windows inside the contest window
BOOKING_START = "2026-08-15T12:00:00Z"
BOOKING_END = "2026-08-15T13:00:00Z"
