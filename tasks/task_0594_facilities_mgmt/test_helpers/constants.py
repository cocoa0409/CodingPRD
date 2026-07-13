"""Domain thresholds and numeric constants stated in the PRD."""

# --- The costing rule (PRD §3.4) ---
STANDARD_LABOR_RATE = 80.00
AFTER_HOURS_MULTIPLIER = 1.5
LABOR_CAP_HOURS = 12
MIN_CALLOUT_AMOUNT = 150.00
PRIORITY_SURCHARGE = {"P1": 0.25, "P2": 0.10, "P3": 0.0, "P4": 0.0}
# Parts markup: <= 500 -> 0.15; > 500 and <= 2000 -> 0.10; > 2000 -> 0.05
PARTS_MARKUP_TIERS = ((500, 0.15), (2000, 0.10), (float("inf"), 0.05))

# --- SLA penalties (PRD §3.5) ---
SLA_RESPONSE_PENALTY_PCT = 0.10
SLA_RESOLVE_PENALTY_PCT = 0.15
SLA_PENALTY_CAP_PCT = 0.25

# --- Vendor standing and performance score (PRD §3.2) ---
PROBATION_STRIKES = 2
SUSPENSION_STRIKES = 3
ROLLING_WINDOW_N = 3
W_RESPONSE = 0.4
W_RESOLVE = 0.3
W_QA = 0.3

# --- Capital project contingency tiers (PRD §3.3) ---
# base_cost <= 100000 -> 0.10; <= 500000 -> 0.07; else 0.05
CONTINGENCY_TIERS = ((100_000, 0.10), (500_000, 0.07), (float("inf"), 0.05))

# --- Building operating posture (PRD §2.8) ---
FROZEN_OOS_CRITICAL_THRESHOLD = 1
RESTRICTED_OPEN_P1_THRESHOLD = 2

# --- Asset condition score (PRD §3.1) ---
RUNTIME_DECAY_BLOCK_HOURS = 1000
RUNTIME_DECAY_POINTS = 5
FAILURE_PENALTY_POINTS = 12
RETIREMENT_SCORE_THRESHOLD = 20

# --- Preventive-maintenance promotion during the epoch run (PRD §3.8) ---
PM_DEFAULT_HOURS = 3
PM_DEFAULT_PARTS = 200.00

# --- Occupancy shares (PRD §2.10, §3.9) ---
MAX_SPACE_SHARE_PCT = 100

# --- Pagination (PRD §2.3) ---
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# --- The logical clock (PRD §2.4) ---
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

# Handy clock anchors used across the suite.
BUSINESS_HOURS_CLOCK = "2026-05-04T09:00:00Z"
AFTER_HOURS_CLOCK = "2026-05-04T19:00:00Z"

TEST_DEFAULTS = {
    "GROSS_AREA_SQM": 1000,
    "VENDOR_HOURLY_RATE": 100.00,
    "SLA_RESPONSE_MINUTES": 60,
    "SLA_RESOLVE_MINUTES": 240,
    "BASE_RATE_PER_SQM_MONTH": 10.00,
}
