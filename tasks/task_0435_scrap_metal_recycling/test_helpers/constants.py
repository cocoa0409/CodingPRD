"""Domain thresholds — numeric constants from PRD calculations."""

# The cumulative cash threshold (in cents) above which a 1099 is required for a
# seller. PRD §3.5: a post-increment total at or above 60000 cents (=$600.00)
# triggers requires_1099 / form_1099_issued; 59999 does not.
TIN_1099_THRESHOLD_CENTS = 60000

# Convenience grade/price defaults used by fixtures and tests. These mirror the
# spot/mill prices the design recipes use to produce the pinned expected values.
TEST_DEFAULTS = {
    # SHRED_STEEL — a FERROUS grade, spot 11c/lb, mill 14c/lb.
    "SHRED_STEEL_SPOT": 11,
    "SHRED_STEEL_MILL": 14,
    # CU_BARE_BRIGHT — a NON_FERROUS grade, spot 375c/lb, mill 410c/lb.
    "CU_SPOT": 375,
    "CU_MILL": 410,
    # BRASS — a NON_FERROUS grade at 100c/lb spot.
    "BRASS_SPOT": 100,
    "BRASS_MILL": 110,
}
