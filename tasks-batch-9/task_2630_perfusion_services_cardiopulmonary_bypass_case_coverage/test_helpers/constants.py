"""Numeric and temporal constants declared by the PRD's business rules.

Every value here is stated in the PRD; nothing is inferred.
"""

# ─── Logical clock ────────────────────────────────────
# The clock starts at exactly 2026-08-01T00:00:00Z on a freshly started server.
INITIAL_CLOCK = "2026-08-01T00:00:00Z"

# ─── Pagination ───────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Case fee ─────────────────────────────────────────
# Prolonged pump time above the contract threshold is billed in whole
# thirty-minute units.
PROLONGED_UNIT_MINUTES = 30
# Acuity uplift percentages applied to the base per-case fee.
ACUITY_UPLIFT_PCT = {
    "ELECTIVE": 0.00,
    "URGENT": 0.10,
    "EMERGENT": 0.25,
}

# ─── Perfusionist readiness score ─────────────────────
CREDIT_WEIGHT = 0.55
EXPERIENCE_WEIGHT = 0.45
READINESS_EXPERIENCE_TARGET = 150
FATIGUE_CASE_WEIGHT = 0.08
FATIGUE_ECMO_WEIGHT = 0.02
READINESS_MIN_ADMISSION = 0.600
READINESS_AUDIT_FLOOR = 0.550
READINESS_DECIMAL_PLACES = 3

# ─── Continuing education ledger ──────────────────────
REMEDIATION_CREDIT_HOURS = 8.0
CE_DECIMAL_PLACES = 1

# ─── Disposable packs ─────────────────────────────────
MAX_SUBSTITUTIONS_PER_PACK = 6

# ─── Devices ──────────────────────────────────────────
DEVICE_TURNAROUND_MINUTES = 90
MAX_CONCURRENT_STAFFED_CASES = 2

# ─── Coverage posture ─────────────────────────────────
COVERAGE_HORIZON_HOURS = 72
COVERAGE_HORIZON_MINUTES = 4320
BACKUP_COVERAGE_MIN_RATIO = 0.5
BACKUP_COVERAGE_MIN_MINUTES = 2160
THIN_PRIMARY_MIN_RATIO = 0.5
THIN_PRIMARY_MIN_MINUTES = 2160

# ─── ECMO runs ────────────────────────────────────────
ECMO_MODE_UPLIFT_PCT = {
    "VV": 0.00,
    "VA": 0.15,
    "VAV": 0.30,
}
ECMO_PROLONGED_HOUR_THRESHOLD = 24
ECMO_RELIEF_WARN_MINUTES = 600
ECMO_MAX_UNINTERRUPTED_MINUTES = 720

# ─── Monthly settlement ───────────────────────────────
VOLUME_TIER_1_CENTS = 5000000
VOLUME_TIER_1_PCT = 0.03
VOLUME_TIER_2_CENTS = 10000000
VOLUME_TIER_2_PCT = 0.06
QUALITY_CREDIT_PER_SYSTEMIC_CENTS = 150000

# ─── Incident review ──────────────────────────────────
MAX_INCIDENT_RETURNS = 2
