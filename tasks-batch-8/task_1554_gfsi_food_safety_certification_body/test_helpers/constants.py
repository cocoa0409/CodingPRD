"""Domain thresholds and shared fixtures values.

The scheme constants below are the rule constants a SchemeAdmin registers
(PRD §3.1); the audit-score weights come from the scoring narrative
(PRD §2.9). Logical timestamps derive from the clock default and the
window/validity arithmetic described in PRD §2.6, §3.3 and §3.6.
"""

# Logical clock startup value (PRD §2.6: "At startup the logical clock reads
# 2026-08-01T00:00:00Z").
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# Pinned scheme rule constants used across the suite (PRD §3.1).
SCHEME_DEFAULTS = {
    "code": "SQF",
    "name": "SQF Food Safety",
    "supported_category_codes": ["BAKERY", "DAIRY", "MEAT"],
    "critical_nc_days": 7,
    "major_nc_days": 28,
    "minor_nc_days": 84,
    "pass_score": 70,
    "unannounced_every_n": 3,
    "unannounced_min_window_days": 60,
    "announced_max_window_days": 30,
    "min_audit_gap_days": 30,
    "cert_validity_days": 1095,
    "witness_validity_days": 365,
    "appeal_window_days": 14,
    "max_cap_rejections": 3,
    "rotation_limit": 2,
    "base_fee": 2000.00,
    "per_category_fee": 333.33,
    "day_rate": 1000.00,
    "unannounced_uplift_pct": 0.10,
    "high_risk_multiplier": 1.5,
}

# Audit-score weights (PRD §2.9): CRITICAL 25, MAJOR 10, MINOR 3, base 100.
SCORE_WEIGHTS = {"CRITICAL": 25, "MAJOR": 10, "MINOR": 3}
SCORE_BASE = 100

# Default product-category scope: one STANDARD BAKERY entry (PRD §3.3).
DEFAULT_SCOPE = [{"category_code": "BAKERY", "risk_tier": "STANDARD"}]

# A passing witness audit recorded before the default clock so the auditor is
# calibration CURRENT at the default logical time (PRD §3.2).
WITNESS_PASS_DATE = "2026-07-01T00:00:00Z"

# Window geometry of the INITIAL audit auto-created when acceptance happens at
# the default clock (PRD §3.3: window_start fourteen days after reviewed_at,
# window_end announced_max_window_days after that start).
AUDIT1_WINDOW_START = "2026-08-15T00:00:00Z"
AUDIT1_WINDOW_END = "2026-09-14T00:00:00Z"
AUDIT1_START_AT = "2026-08-15T09:00:00Z"

# The auto-projected second audit (SURVEILLANCE): window_start is the later of
# decided_at + 14d and prior window_end + min_audit_gap_days (PRD §3.6).
AUDIT2_WINDOW_START = "2026-10-14T00:00:00Z"
AUDIT2_WINDOW_END = "2026-11-13T00:00:00Z"
AUDIT2_START_AT = "2026-10-14T09:00:00Z"

# Third audit of the chain when unannounced_every_n == 3 (PRD §3.6).
AUDIT3_WINDOW_START = "2026-12-13T00:00:00Z"
AUDIT3_WINDOW_END = "2027-02-11T00:00:00Z"

# Certificate validity horizon: valid_from 2026-08-15T09:00:00Z plus
# cert_validity_days 1095 (PRD §3.6).
CERT_VALID_FROM = "2026-08-15T09:00:00Z"
CERT_VALID_TO = "2029-08-14T09:00:00Z"
