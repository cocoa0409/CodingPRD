"""Domain thresholds — numeric constants from the PRD's rules (§2.6, §2.10, §3).

Values are named exactly as the PRD prose pins them.
"""

# Logical clock (PRD §2.5)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Clash severity classification (PRD §3.4: boundary at 50.0 mm, strictly greater)
CRITICAL_OVERLAP_MM = 50.0

# As-built verification tolerance (PRD §3.7: at most 25.0 mm verifies)
AS_BUILT_TOLERANCE_MM = 25.0

# Freeze-member audit floor (PRD §3.3: audit_score at least 70.0)
AUDIT_ACCEPT_THRESHOLD = 70.0

# Provisional cost tariff (PRD §3.4)
BASE_HOURS_CRITICAL = 40
BASE_HOURS_MAJOR = 16
BASE_HOURS_MINOR = 4
SPANS_MULTIPLIER = 1.5

# Coordination readiness index (PRD §2.6)
CRI_BASE = 100
W_CRITICAL = 25
W_MAJOR = 10
W_MINOR_UNASSIGNED = 5
W_OVERDUE_COMMITMENT = 15
CRI_HOLD_THRESHOLD = 60
CRI_RELEASE_THRESHOLD = 85

# Partner reliability decay (PRD §3.5)
TIER_A_FLOOR = 80
TIER_B_FLOOR = 50
PENALTY_A = 5
PENALTY_B = 10
PENALTY_C = 20
PROBATION_THRESHOLD = 40
RELIABILITY_START = 100

# Audit score class weights (PRD §3.2)
W_LIFE_SAFETY = 0.5
W_ENVELOPE = 0.3
W_FINISH = 0.2

# Freeze window coordination buffer (PRD §3.3: 3,600 seconds)
FREEZE_GAP_SECONDS = 3600

# LOD requirement allowed values (PRD §3.1)
ALLOWED_MIN_LOD = (100, 200, 300, 350, 400, 500)

# Phase order (PRD §3.1)
PHASE_ORDER = (
    "SCHEMATIC_DESIGN",
    "DESIGN_DEVELOPMENT",
    "CONSTRUCTION_DOCUMENTS",
    "CONSTRUCTION_ADMINISTRATION",
    "CLOSEOUT",
)

TEST_DEFAULTS = {
    "HOURLY_RATE_CENTS": 12000,
    "COORDINATION_BUDGET_HOURS": 100.0,
    "RUN_TOLERANCE_MM": 5.0,
}
