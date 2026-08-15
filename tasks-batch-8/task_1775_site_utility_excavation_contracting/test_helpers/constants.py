"""Domain thresholds — numeric constants stated by the PRD."""

# Logical clock (PRD §2.5): the server clock reads this exact instant before
# any client interaction.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Locate tickets (PRD §3.2): validity window length in hours (28 days).
TICKET_VALIDITY_HOURS = 672

# Pothole adjudication tolerances (PRD §3.2), inches; both inclusive.
POTHOLE_DEPTH_TOLERANCE_IN = 6
POTHOLE_OFFSET_TOLERANCE_IN = 12

# Trench slope requirements by soil class (PRD §3.3); boundary inclusive.
SLOPE_RATIO_REQUIRED = {"SOIL_A": 0.75, "SOIL_B": 1.0, "SOIL_C": 1.5}
# Depth at or above which an engineered system is mandatory (PRD §3.3).
ENGINEERED_DEPTH_FT = 20

# Backfill lift geometry (PRD §3.4), feet.
LIFT_THICKNESS_FT = 1.0
BEDDING_DEPTH_FT = {"CLASS_B": 0.5, "CLASS_C": 0.5, "CLASS_D": 0.25}

# Compaction acceptance thresholds by bedding class (PRD §3.4); inclusive.
REQUIRED_COMPACTION_PCT = {"CLASS_B": 95.0, "CLASS_C": 90.0, "CLASS_D": 85.0}

# Installation inspection tolerances (PRD §3.4); slope boundary inclusive.
INSPECTION_SLOPE_TOLERANCE_PCT = 0.2
INSPECTION_MIN_COVER_FT = 0.5

# Change-order pricing tiers (PRD §3.8), integer cents.
TIER1_LIMIT_CENTS = 2_500_000
TIER1_RATE = 0.15
TIER2_LIMIT_CENTS = 10_000_000
TIER2_RATE = 0.10
TIER3_RATE = 0.05
# Amount gate on change-order review (PRD §3.8): at or above this provisional
# price the owner rep decides; below it the project manager decides.
CO_REVIEW_THRESHOLD_CENTS = 2_500_000

# As-built acceptance tolerances (PRD §3.9); both boundaries inclusive.
ASBUILT_MIN_LENGTH_TOL_FT = 1.0
ASBUILT_LENGTH_TOL_RATE = 0.01
ASBUILT_MIN_INVERT_TOL_FT = 0.1
ASBUILT_INVERT_TOL_RATE = 0.005

# Shutdown window project clearance (PRD §3.5), minutes; exactly this passes.
PROJECT_WINDOW_BUFFER_MINUTES = 120
