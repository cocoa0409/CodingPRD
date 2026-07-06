"""Domain thresholds — numeric constants from the PRD calculations and workflows."""

# Impact-fee schedule rates used across the fee tests (PRD §3.8).
FEE_SCHEDULE_DEFAULTS = {
    "park_fee_per_lot_cents": 250000,
    "road_fee_tier1_per_acre_cents": 120000,
    "road_fee_tier2_per_acre_cents": 90000,
    "road_fee_tier3_per_acre_cents": 60000,
    "admin_pct": 0.05,
    "affordable_discount_pct": 0.20,
    "credit_pct": 0.10,
    "fee_cap_cents": 10000000,
}

# Tier boundaries in acres (PRD §3.8): first band 0-5, middle band 5-20, top band > 20.
TIER1_BOUND_ACRES = 5
TIER2_BOUND_ACRES = 20

# Date arithmetic constants (PRD §3.5 / §3.7).
APPEAL_WINDOW_DAYS = 15
ENTITLEMENT_DAYS = {
    "VARIANCE": 730,
    "CUP": 730,
    "SUBDIVISION": 1095,
    "REZONE": None,
}
EXTENSION_DAYS = 365
MAX_EXTENSIONS = 1

# Statutory notice minimums per hearing body, in whole days (PRD §3.4).
NOTICE_MIN_DAYS = {
    "PLANNING_COMMISSION": 10,
    "CITY_COUNCIL": 15,
}

# Minimum gap between same-body hearings, in whole days (PRD §3.4).
BODY_MIN_GAP_DAYS = 14

# Startup logical-clock default (PRD §2.4).
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

# Canonical timeline reused by pipeline fixtures.
CLOCK_DECISION_BASE = "2026-06-01T00:00:00Z"   # notice mailed / decision recorded here
HEARING_DATE = "2026-06-11T00:00:00Z"          # exactly 10 days after the notice (PC minimum)
APPEAL_DEADLINE = "2026-06-16T00:00:00Z"       # decision_at + 15 days
CLOCK_AFTER_WINDOW = "2026-06-17T00:00:00Z"    # strictly past the appeal deadline
