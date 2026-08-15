"""Domain thresholds and constants — numeric rules from PRD §2.5, §3.2, §3.4, §3.8, §3.9."""

# Startup logical clock (PRD §2.5)
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Chargeable weight (PRD §3.2)
VOLUMETRIC_FACTOR = 167.0  # kg per m3

# Demurrage tiers (PRD §3.8)
DEMURRAGE_FREE_DAYS = 3
DEMURRAGE_TIER1_DAYS = 4
DEMURRAGE_TIER1_RATE = 50.00
DEMURRAGE_TIER2_RATE = 120.00

# Claim settlement (PRD §3.9)
LIABILITY_RATE_PER_KG = 19.00

# Build-window separation buffer (PRD §3.4)
BUILD_WINDOW_BUFFER_MINUTES = 30

# Canonical build window used by composite fixtures
DEFAULT_BUILD_START = "2026-08-09T10:00:00Z"
DEFAULT_BUILD_END = "2026-08-09T12:00:00Z"

# Canonical flight schedule used by composite fixtures
DEFAULT_DEPARTURE = "2026-08-10T08:00:00Z"
DEFAULT_ARRIVAL = "2026-08-12T08:00:00Z"

# Default acting operator identifiers (opaque per PRD §2.1)
FWD_USER_1 = "fwd-1"
FWD_USER_2 = "fwd-2"
DG_INSPECTOR_USER = "dg-9"
