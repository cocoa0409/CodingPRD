"""Domain thresholds and reference constants (PRD §2.4, §2.8, §3.2, §3.3, §3.5, §3.6, §3.9)."""

# Logical clock startup default (PRD §2.4)
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Electrical reference tables (PRD §2.8)
U0_KV = {"KV_15": 8.7, "KV_25": 14.4, "KV_35": 20.3, "KV_69": 39.8}
VF_STD = {"KV_15": 0.52, "KV_25": 0.52, "KV_35": 0.52, "KV_69": 0.53}
CALIBRATED_VF_RANGE = (0.45, 0.60)

# Series verdict thresholds (PRD §3.6)
TD_PASS_MAX = 5.0        # PASS when max rounded tan-delta is strictly below this
TD_FAIL_MIN = 80.0       # FAIL when max rounded tan-delta reaches or exceeds this
TIP_UP_FAIL = 12.0       # FAIL when step-2 minus step-0 reaches or exceeds this
PD_MONITOR_MIN = 500     # MONITOR when max PD reaches or exceeds this
PD_FAIL_MIN = 2000       # FAIL when max PD reaches or exceeds this

# Temperature correction (PRD §3.6): k(T) = clamp(1 + (20 - T) * 0.01, 0.9, 1.1)
TEMP_CORR_FACTOR_MIN = 0.9
TEMP_CORR_FACTOR_MAX = 1.1
TEMP_CORR_REFERENCE_C = 20.0

# Fault pinpointing (PRD §3.7)
VELOCITY_M_PER_US = 300
CORRIDOR_MIN_M = 5.0
CORRIDOR_FRACTION = 0.10

# Outage overrun charge (PRD §3.2)
GRACE_MIN = 15
RATE_T1_CENTS_PER_MIN = 400   # first 60 chargeable minutes
RATE_T2_CENTS_PER_MIN = 650   # next 120 chargeable minutes
RATE_T3_CENTS_PER_MIN = 900   # beyond 180 chargeable minutes
TIER1_MAX_MIN = 60
TIER2_MAX_MIN = 120
EMERGENCY_MULT = 1.25         # EMERGENCY_FAULT windows
ESTIMATE_OVERRUN_FRACTION = 0.10

# Job estimate (PRD §3.3)
CALLOUT_CENTS = 180000
PER_METER_CENTS = 125
METHOD_FEE_CENTS = {"VLF_TAN_DELTA": 95000, "VLF_WITH_PD": 145000, "PD_MAPPING": 120000}
COMPLEX_THRESHOLD_CENTS = 400000   # strictly greater than this -> COMPLEX
RATE_COMPLEX = 0.12
RATE_STANDARD = 0.06

# Invoice markup (PRD §3.3)
INVOICE_MARKUP = 0.085

# Equipment (PRD §3.5)
UNIT_BUFFER_HOURS = 4
CURING_HOURS = 24

# Health assessment weights and bands (PRD §3.9)
W_TD = 0.35
W_PD = 0.30
W_FAULT = 0.20
W_AGE = 0.15
AGE_FREE_YEARS = 25
AGE_PEN_PER_YEAR = 5
BAND_GOOD_MIN = 80.0
BAND_FAIR_MIN = 60.0
BAND_POOR_MIN = 40.0

# Derived: 1.5 x U0 per class = nominal VLF test voltage (PRD §3.6)
VLF_TEST_VOLTAGE_KV = {cls: 1.5 * u0 for cls, u0 in U0_KV.items()}
# KV_15 -> 13.05 kV nominal; +/-5% inclusive tolerance
KV15_TEST_VOLTAGE = 13.05
KV15_TEST_VOLTAGE_MAX = 13.7025   # exactly +5%, accepted
KV15_TEST_VOLTAGE_OVER = 13.7026  # rejected

# Standard scenario timestamps used by the composite fixtures.
WINDOW_START = "2026-08-10T08:00:00Z"
WINDOW_END = "2026-08-12T12:00:00Z"
MOBILIZE_AT = "2026-08-10T07:00:00Z"
DEMOBILIZE_AT = "2026-08-12T12:00:00Z"
CLOCK_IN_WINDOW = "2026-08-10T09:00:00Z"
DIG_START = "2026-08-10T09:30:00Z"
DIG_END = "2026-08-10T11:00:00Z"
CLOCK_DIG = "2026-08-10T09:45:00Z"
CLOCK_AFTER_CURING = "2026-08-11T10:00:00Z"   # > 24h after cure at 09:45 on 08-10
CLOCK_RETEST = "2026-08-11T10:05:00Z"        # strictly after completed_at
