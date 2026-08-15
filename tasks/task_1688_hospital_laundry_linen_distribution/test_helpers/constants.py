"""Domain thresholds and shared test constants (PRD 2.x / 3.x)."""

THRESHOLDS = {
    # Shrinkage investigation fires when the cumulative loss rate reaches or
    # exceeds this percentage (PRD 3.5).
    "LOSS_RATE_INVESTIGATION_PCT": 5.00,
    # Minimum clear gap between cart-run windows of the same unit (PRD 3.2).
    "RUN_WINDOW_BUFFER_MINUTES": 120,
    # Unit quality standing: this many verified/resolved complaints inside the
    # trailing window flips the unit to WATCH (PRD 3.7).
    "WATCH_COMPLAINT_COUNT": 3,
    "WATCH_WINDOW_DAYS": 30,
    # CRITICAL-posture stock halving factor for STANDARD units (PRD 3.3).
    "CRITICAL_TRIAGE_DIVISOR": 2,
}

# Standard contract terms reused across scenarios: 40 cents/lb wash rate with
# a 0.25 isolation surcharge fraction.
TEST_DEFAULTS = {
    "FACILITY_NAME": "General",
    "RATE_PER_LB_CENTS": 40,
    "ISOLATION_SURCHARGE_PCT": 0.25,
    # Workhorse sheet stock: 2.00 lbs/piece -> 80 cents/piece at the standard
    # rate; 50-cycle wash life; reorder point 20; 100 opening + 10 reserve.
    "SHEET_SKU": "SHEET-T",
    "SHEET_NAME": "Flat Sheet",
    "SHEET_WEIGHT_LBS": 2.00,
    "SHEET_UNIT_COST_CENTS": 500,
    "SHEET_MAX_WASH_CYCLES": 50,
    "SHEET_REORDER_POINT": 20,
    "SHEET_OPENING_PIECES": 100,
    "SHEET_OPENING_RESERVE": 10,
    # Isolation gown: 0.50 lbs/piece -> 20 cents/piece at the standard rate.
    "GOWN_SKU": "ISO-GOWN",
    "GOWN_NAME": "Isolation Gown",
    "GOWN_WEIGHT_LBS": 0.50,
    "GOWN_UNIT_COST_CENTS": 300,
    "GOWN_MAX_WASH_CYCLES": 30,
    "GOWN_REORDER_POINT": 10,
    "GOWN_OPENING_PIECES": 200,
    "GOWN_OPENING_RESERVE": 20,
    # Terry towel: 0.75 lbs/piece -> 30 cents/piece at the standard rate.
    "TOWEL_SKU": "TOWEL",
    "TOWEL_NAME": "Bath Towel",
    "TOWEL_WEIGHT_LBS": 0.75,
    "TOWEL_UNIT_COST_CENTS": 150,
    "TOWEL_MAX_WASH_CYCLES": 40,
    "TOWEL_REORDER_POINT": 15,
    "TOWEL_OPENING_PIECES": 120,
    "TOWEL_OPENING_RESERVE": 0,
}

# Canonical schedule anchors used by the composite fixtures. Runs on the same
# unit are always separated by at least the required two-hour buffer.
TIME_FILL_START = "2026-08-02T08:00:00Z"
TIME_FILL_END = "2026-08-02T09:00:00Z"
TIME_COLLECT_START = "2026-08-02T11:00:00Z"
TIME_COLLECT_END = "2026-08-02T12:00:00Z"
CLOCK_AT_SCHEDULING = "2026-08-02T08:00:00Z"
PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-08-07T00:00:00Z"
PERIOD_ADJUSTED_PATIENT_DAYS = 50
