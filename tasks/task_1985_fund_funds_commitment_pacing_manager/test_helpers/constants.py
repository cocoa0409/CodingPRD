"""Domain thresholds — numeric constants from PRD calculations (§2.9, §3)."""

# program_posture (PRD §2.4): low-cash band triggers strictly below 1.10x buffer.
LOW_CASH_BAND = 1.10

# dd_composite_score (PRD §3.3): fixed weights and inclusive approval threshold.
W_STRATEGY = 0.30
W_TRACK = 0.25
W_OPS = 0.25
W_COMPLIANCE = 0.20
DD_APPROVAL_THRESHOLD = 70

# nav_rollup (PRD §3.8): lag policy window in days after quarter end.
LAG_DAYS = 90

# fee_layering (PRD §3.8): wrapper rate and the nav floor.
WRAPPER_RATE = 0.005
FEE_EPSILON = 0.01

# capital_call_forecast (PRD §3.6): forecast horizon and stress scaling.
FORECAST_QUARTERS = 8
STRESS_CALL_SCALE = 1.15

# pacing_targets (PRD §3.2): max entries in target_strategy_mix.
MAX_MIX_ENTRIES = 4

# Commitment sizing band (PRD §3.4): sized_amount within +/-10% of proposed.
SIZE_BAND_LOW = 0.90
SIZE_BAND_HIGH = 1.10

# Logical clock (PRD §2.9): seeded startup instant.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
