"""Domain thresholds and shared values from the PRD's calculation narratives."""

# PRD §2.4 — startup logical clock reading.
STARTUP_CLOCK_ISO = "2026-05-01T00:00:00Z"
# Conventional clock pin used by scenario fixtures.
BASE_CLOCK_ISO = "2026-05-01T08:00:00Z"

# PRD §3.1 — shop configuration defaults applied when omitted at creation.
SHOP_DEFAULTS = {
    "stall_daily_hours": 8,
    "dwell_free_hours": 48,
    "warranty_days": 90,
    "counter_window_days": 30,
    "owner_watch_threshold_cents": 1_000_000,
}

# PRD §2.8 — Rule 5 interchange-damage window.
INTERCHANGE_DAMAGE_WINDOW_HOURS = 24

# PRD §2.5 — capacity posture ratios.
CONSTRAINED_RATIO = 0.85

# PRD §3.8 — aggregate counter-bill ceiling fraction of submitted_total_cents.
AGGREGATE_COUNTER_CAP_PCT = 0.60

# PRD §3.6 — wheelset condemnation limits (inclusive on both).
MIN_FLANGE_MM = 28.0
MAX_TREAD_WEAR_MM = 9.5

# Standard price-master entries reused across scenarios.
ENTRY_AIR_HOSE = {
    "job_code": "J-AIR-HOSE",
    "description": "Air hose replacement",
    "labor_rate_cents_per_hour": 9000,
    "mobile_labor_rate_cents_per_hour": 11000,
    "standard_labor_hours": 1.5,
    "mobile_trip_surcharge_cents": 25000,
    "mobile_eligible": True,
    "effective_from": "2026-01-01",
    "effective_to": "2026-12-31",
}

ENTRY_INSPECT_MINOR = {
    "job_code": "J-INSPECT-MINOR",
    "description": "Minor inspection labor",
    "labor_rate_cents_per_hour": 3333,
    "mobile_labor_rate_cents_per_hour": 4000,
    "standard_labor_hours": 0.9,
    "mobile_trip_surcharge_cents": 0,
    "mobile_eligible": True,
    "effective_from": "2026-01-01",
    "effective_to": "2026-12-31",
}

# Standard defects reused across scenarios.
DEFECT_AIR_HOSE = {
    "aar_defect_code": "AAR-1204",
    "defect_group": "AIR_HOSE",
    "cause_code": "WEAR",
    "severity": "MAJOR",
    "location": "A-end",
}

DEFECT_OTHER_MINOR = {
    "aar_defect_code": "AAR-9001",
    "defect_group": "OTHER",
    "cause_code": "WEAR",
    "severity": "MINOR",
    "location": "A-end",
}

# A default future slot window relative to BASE_CLOCK_ISO.
DEFAULT_SLOT_START = "2026-05-02T08:00:00Z"
DEFAULT_SLOT_END = "2026-05-02T16:00:00Z"

# Opaque operator identities used throughout the scenarios.
FOREMAN_USER_ID = "foreman-1"
QI_USER_ID = "qi-1"
