"""Domain thresholds — numeric constants from the PRD calculations (§2.6, §3)."""

# Minimum acceptable Test Uncertainty Ratio (PRD §3.4): when tur is below 4.0 and
# the base outcome is not already FAIL, the result is forced to FAIL.
MIN_TUR = 4.0

# Gage R&R AIAG constants (PRD §3.7).
K1_BY_TRIAL_COUNT = {2: 4.56, 3: 3.05, 4: 2.50}
K2_BY_OPERATOR_COUNT = {2: 3.65, 3: 2.70, 4: 2.30}

# %GRR acceptability thresholds (PRD §3.7): ACCEPTABLE <= 10.00; MARGINAL in
# (10.00, 30.00]; UNACCEPTABLE > 30.00.
GRR_ACCEPTABLE_PCT = 10.00
GRR_MARGINAL_PCT = 30.00

# Maximum traceability chain depth (PRD §2.8).
MAX_TRACEABILITY_DEPTH = 10

# Minimum points for the LSQ drift method to be meaningful (PRD §3.8).
MIN_POINTS_FOR_LSQ = 2

# The boot value of the logical clock (PRD §2.4): current_epoch == 0 maps to
# 2026-01-01T00:00:00Z.
CLOCK_BOOT_EPOCH = 0

# Convenience defaults mirroring the design recipes (instrument nominal 25.0,
# tolerance band 0.10 = tolerance_plus 0.05 + tolerance_minus 0.05).
TEST_DEFAULTS = {
    "INST_NOMINAL": 25.0,
    "TOL_PLUS": 0.05,
    "TOL_MINUS": 0.05,
    "INTERVAL": 100,
    "STD_UNCERTAINTY": 0.001,
    "STD_NOMINAL": 25.0,
    "GRR_PROCESS_TOLERANCE": 10.0,
}
