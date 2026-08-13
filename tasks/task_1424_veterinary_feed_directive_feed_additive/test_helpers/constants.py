"""Domain thresholds and defaults from PRD calculations (§2.5, §2.8, §2.9, §3.8)."""

# Logical clock default at server startup (PRD §2.5)
DEFAULT_START_CLOCK = "2026-08-01T00:00:00Z"

# Compliance scoring (PRD §2.9)
INITIAL_COMPLIANCE_SCORE = 1000
AUDIT_READY_SCORE_THRESHOLD = 700

# Residue severity tier ratio bounds (PRD §3.8)
TIER_1_MAX_RATIO = 2.0
TIER_2_MAX_RATIO = 5.0

# Compliance penalty schedule (PRD §3.8): per-tier marginal rates + flat admin penalty
TIER_1_RATE = 50
TIER_2_RATE = 150
TIER_3_RATE = 400
FLAT_ADMIN_PENALTY = 100

# VFD issuance constraint (PRD §3.3, 21 CFR 558.6)
MAX_VFD_DURATION_MONTHS = 6

# Pagination (PRD §2.3)
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# Common fixture values
DEFAULT_VCPR_EXPIRES_ON = "2027-08-01T00:00:00Z"
DEFAULT_VFD_EXPIRATION = "2026-10-01T00:00:00Z"
DEFAULT_STATE_CODE = "IA"
