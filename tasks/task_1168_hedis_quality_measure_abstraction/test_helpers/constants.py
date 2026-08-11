"""Domain thresholds and pinned constants (PRD §2.5, §2.7, §3.4, §3.5, §3.7)."""

# Logical clock startup default (PRD §2.5: "the clock reads exactly 2026-05-01T00:00:00Z").
DEFAULT_LOGICAL_CLOCK = "2026-05-01T00:00:00Z"

# Rate / IRR precision (PRD §2.7: 4 decimal places, rounded half-up).
RATE_DECIMALS = 4

# IRR tier thresholds (PRD §3.5).
IRR_PASS_THRESHOLD = 0.95
IRR_MID_TIER = 0.90
BASE_OVERREAD_FRACTION = 0.10
MID_OVERREAD_FRACTION = 0.25
FULL_OVERREAD_FRACTION = 1.0
REMEDIATION_OVERRIDE_COUNT = 2

# Spec defaults (PRD §3.1).
DEFAULT_HYBRID_POLICY = "SAMPLE_ONLY"
DEFAULT_MATCHING_POLICY = "EXACT"
DEFAULT_SAMPLE_SIZE_FLOOR = 411
DEFAULT_GENDER_REQUIREMENT = "ANY"
DEFAULT_ALLOWABLE_GAP_DAYS = 45
DEFAULT_REPORTING_WEIGHT = 1.0

# Eligibility (PRD §3.3): at most one enrollment gap inside the window.
MAX_GAPS_ALLOWED = 1

# Gap-burden per-line precision (PRD §3.7: 2 decimal places per line, then sum).
BURDEN_LINE_DECIMALS = 2

# Standard measurement-year service window for MY2025 (PRD §3.6).
MY2025_SERVICE_WINDOW = ("2025-01-01", "2025-12-31")
