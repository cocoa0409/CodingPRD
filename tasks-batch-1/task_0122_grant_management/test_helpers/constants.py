"""Domain thresholds and numeric constants from the Grant Management PRD calculations."""

# PRD §3.8: Single Audit threshold is seven hundred fifty thousand dollars,
# inclusive boundary (>=). 74,999,999 -> false; 75,000,000 -> true.
SINGLE_AUDIT_THRESHOLD_CENTS = 75_000_000

# PRD §3.3 / §3.6: MTDC excludes the portion of each subaward pass-through line
# that exceeds twenty-five thousand dollars.
SUBAWARD_EXCLUSION_CAP_CENTS = 2_500_000

# PRD §3.3: the standard ten-percent (DE_MINIMIS) indirect-cost rate.
DE_MINIMIS_RATE = 0.10

# PRD §3.1: federal_share_pct defaults to 0.80 when omitted.
DEFAULT_FEDERAL_SHARE_PCT = 0.80
