"""Domain thresholds and shared values (PRD §2.6, §2.7, §2.8, §3.8)."""

# Logical clock defaults (PRD §2.11: default instant 2026-05-01T00:00:00Z)
DEFAULT_CLOCK_ISO = "2026-05-10T09:00:00Z"
DEFAULT_SESSION_START = "2026-05-11T10:00:00Z"

# Hold TTL (PRD §2.6: creation time plus fifteen minutes)
HELD_TTL_MINUTES = 15

# Loudness compliance (PRD §2.8)
LUFS_TOLERANCE = 0.5

# Money / pricing (PRD §2.7)
BASIS_POINTS_SCALE = 10000

# Recall fee schedule (PRD §3.8)
RECALL_FEE_PER_GB_CENTS = {
    "HOT": 500,
    "WARM": 1000,
    "COLD": 2000,
    "GLACIER": 4000,
}
RECALL_MIN_FEE_CENTS = 1000
GB_BYTES = 1073741824

# Time grid (PRD §2.6)
SLOT_BOUNDARY_MINUTES = (0, 30)
MIN_DURATION_MINUTES = 60
MAX_DURATION_MINUTES = 480

# Shared test payload values
DEFAULT_UPC = "012345678901"
DEFAULT_ISRC = "USRC17607839"
