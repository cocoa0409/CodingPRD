"""Domain thresholds — numeric constants stated verbatim in the PRD.

Only constants the PRD spells out in prose are included here. The clinical
safety-gate thresholds (minimum residual bed, maximum safe keratometry,
maximum treatable diopters, minimum age, heal-settling days) are deliberately
NOT defined: the PRD names them only abstractly and never states their values,
so no PRD-only assertion may depend on them.
"""

# Ablation-depth estimate (PRD §3.4/§2.6).
OPTICAL_ZONE_MM = 1.0
DEPTH_PER_DIOPTER_UM = 12.0

# Residual stromal bed (PRD §3.4).
FLAP_THICKNESS_UM = 110

# Refund payout (PRD §3.9).
GUARANTEE_FEE_CENTS = 25000

# Amortized installment (PRD §3.4): apr_bps / 10000 / 12.
APR_BPS_DIVISOR = 10000

# LIFETIME enhancement window (PRD §3.1).
LIFETIME_WINDOW_DAYS = 36500

# Logical clock startup default (PRD §2.7).
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# A syntactically valid UUID that does not resolve to any entity.
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
