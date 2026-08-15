"""Domain thresholds and fixture constants from the PRD's calculation rules."""

# --- effective_time_standard (PRD §3.3) ---
STAT_CAP_MINUTES = 45

# --- placement_demand_score (PRD §3.2) ---
URGENCY_BASE = {"STAT": 1000, "URGENT": 500, "STANDARD": 100}
WAIT_CAP_MINUTES = 120
WAIT_WEIGHT_PER_MINUTE = 2
SCARCITY_BONUS = 50

# --- clean_request_priority_score (PRD §3.2) ---
TIER_BASE = {"STAT": 10000, "URGENT": 5000, "STANDARD": 0}
BREACH_BOOST = 2500

# --- productivity_score (PRD §3.6) ---
BASE_CREDIT = {"ROUTINE": 1.00, "ISOLATION": 1.50, "TERMINAL": 2.00}
EF_FLOOR = 0.50
EF_CAP = 1.50
QA_FAIL_PENALTY = 5.00
STAT_ELIGIBILITY_THRESHOLD = 80.00

# --- audit_result_determination (PRD §3.6) ---
FLUORESCENT_PASS_FRACTION = 0.85

# --- supply_consumption_bom (PRD §3.5) ---
BOM = {
    "ROUTINE": {"DISINFECTANT": 2, "CLOTH": 4},
    "ISOLATION": {"DISINFECTANT": 4, "PPE_PACK": 2, "CLOTH": 6},
    "TERMINAL": {"DISINFECTANT": 6, "PPE_PACK": 3, "CLOTH": 8, "SEALANT": 1},
}
RECLEAN_CONSUMPTION_RATIO = 0.5

# --- maintenance_capacity_check (PRD §3.9) ---
MAINTENANCE_CAP_PCT = 0.20

# --- staff window buffer rule (PRD §3.4) ---
STAFF_WINDOW_BUFFER_MINUTES = 10

# --- notification expiry (PRD §3.7 / §3.9) ---
NOTIFICATION_EXPIRY_MINUTES = 60

# --- Logical clock default (PRD §2.4) ---
CLOCK_DEFAULT_START = "2026-08-01T00:00:00Z"
CLOCK_T0800 = "2026-08-01T08:00:00Z"

# --- Shared fixture values used across the design indices ---
# CleanStandard rows: (base_minutes, outbreak_multiplier_bps, atp_rlu_threshold)
STANDARD_FIXTURES = {
    "ROUTINE": {"base_minutes": 45, "outbreak_multiplier_bps": 15000, "atp_rlu_threshold": 250},
    "ISOLATION": {"base_minutes": 60, "outbreak_multiplier_bps": 15000, "atp_rlu_threshold": 150},
    "TERMINAL": {"base_minutes": 90, "outbreak_multiplier_bps": 20000, "atp_rlu_threshold": 100},
}
# SupplyItem rows: (initial_on_hand, reorder_threshold)
SUPPLY_FIXTURES = {
    "DISINFECTANT": {"initial_on_hand": 100, "reorder_threshold": 10},
    "PPE_PACK": {"initial_on_hand": 50, "reorder_threshold": 8},
    "CLOTH": {"initial_on_hand": 200, "reorder_threshold": 20},
    "SEALANT": {"initial_on_hand": 20, "reorder_threshold": 2},
}

# A UUID that is never created by any fixture.
BOGUS_UUID = "00000000-0000-0000-0000-000000000000"
