"""Domain thresholds and numeric constants from PRD §2.5, §3.4, §3.5, §3.7, §3.9."""

# §2.5 — Numerical precision
PRECISION_DECIMALS = 4
WEIGHT_TOLERANCE = 0.0001          # |sum - 1.0| <= 0.0001 passes (inclusive)

# §3.4 — Stale threshold
STALE_THRESHOLD_DAYS = 14          # >= 14 full days means stale; strictly less means not stale
SECONDS_PER_DAY = 86_400

# §3.5 — Alignment impact
ATTENUATION = 0.7
UPSTREAM_INFLUENCE = 0.5

# §3.7 — Review thresholds
MIN_CALIBRATION_DELTA = 0.05       # |calibration_score - manager_score| must be STRICTLY GREATER
SELF_WEIGHT = 0.3
MANAGER_WEIGHT = 0.7
CALIBRATION_DELTA_TRIGGER = 0.20   # |manager - self| > 0.20 → use weighted average

# §3.9 — Dedup window
DEDUP_WINDOW_MINUTES = 60
DEDUP_WINDOW_SECONDS = DEDUP_WINDOW_MINUTES * 60

# Pagination defaults (§2.3)
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
