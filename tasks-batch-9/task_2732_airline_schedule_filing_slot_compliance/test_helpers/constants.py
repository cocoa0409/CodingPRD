"""Domain thresholds and shared literals for the schedule filing & slot compliance API.

Every number here is stated in the PRD; nothing is invented.
"""

# ── Logical clock (PRD §2.5) ─────────────────────────────────────────────
# "Before any client has set the clock, it reads exactly 2026-08-01T00:00:00Z"
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ── Pagination (PRD §2.3) ────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# ── Identifiers used for 404 probes ──────────────────────────────────────
MISSING_UUID = "00000000-0000-4000-8000-000000000000"

# ── Filing charge arithmetic (PRD §3.8) ──────────────────────────────────
CHARGE_PER_LEG_CENTS = 4225
VOLUME_SURCHARGE_PCT = {
    "TIER_1_UP_TO_5_LEGS": 0.00,
    "TIER_2_UP_TO_20_LEGS": 12.50,
    "TIER_3_ABOVE_20_LEGS": 22.00,
}
EXPEDITE_RATE_PCT = {
    "STANDARD": 0.00,
    "EXPEDITED": 35.00,
    "EMERGENCY": 80.00,
}
DEFAULT_FILING_CHARGE_BUDGET_CENTS = 100000

# ── Compliance score weights (PRD §3.7) ──────────────────────────────────
SCORE_BASE = 100.00
PENALTY_PER_CURFEW_VIOLATION = 12.00
PENALTY_PER_MCT_VIOLATION = 7.00
PENALTY_PER_GATE_OVERFLOW = 9.00
PENALTY_PER_UNSLOTTED_LEG = 8.00
PENALTY_PER_AT_RISK_SLOT = 15.00
PENALTY_CAP = 100.00
BLOCKED_SCORE_THRESHOLD = 60.00   # strictly below → BLOCKED
WARNED_SCORE_THRESHOLD = 85.00    # strictly below → WARNED

# ── Slot utilization (PRD §3.5 / §3.2) ───────────────────────────────────
UTILIZATION_RETENTION_THRESHOLD_PCT = 80.00
AT_RISK_THRESHOLD_PCT = 80.00
CREDITING_OUTCOMES = ("OPERATED", "CANCELLED_ATC", "RETURNED_IN_TIME")
NON_CREDITING_OUTCOMES = ("CANCELLED_CARRIER", "NOT_OPERATED")

# ── Notification obligations (PRD §3.9) ──────────────────────────────────
OBLIGATION_MIN_MAGNITUDE_MINUTES = 30
MANDATORY_TIER_MAGNITUDE_MINUTES = 120
CANCELLATION_EQUIVALENT_MINUTES = 240
TIER_MULTIPLIER_PCT = {
    "ADVISORY": 37.50,
    "MANDATORY_REACCOMMODATION": 100.00,
}
COMPENSATION_RATE_CENTS = {
    "first": 61500,
    "business": 40252,
    "economy": 25124,
}
NOTIFY_DEADLINE_OFFSET_HOURS = 72

# ── Rotation, turn and connection rules (PRD §3.3 / §3.4) ────────────────
INTERNATIONAL_TURN_SUPPLEMENT_MINUTES = 15
MAX_LEG_ELAPSED_MINUTES = 1080
DEPARTURE_GATE_LEAD_MINUTES = 45
ARRIVAL_GATE_TRAIL_MINUTES = 30
DEFAULT_MIN_CONNECT_DOMESTIC_MINUTES = 35
DEFAULT_MIN_CONNECT_INTERNATIONAL_MINUTES = 60
DEFAULT_MIN_TURN_OVERRIDE_MINUTES = 0

# ── Literal reason strings the PRD pins (PRD §3.4 / §3.7 / §3.9) ─────────
REASON_SCHEDULE_WITHDRAWN = "SCHEDULE_WITHDRAWN"
REASON_SCHEDULE_BLOCKED = "SCHEDULE_BLOCKED"
REASON_CHANGE_REVERTED = "CHANGE_REVERTED"

# ── Season calendar used by every fixture ────────────────────────────────
SEASON_CODE = "W26"
SEASON_START_DATE = "2026-10-25T00:00:00Z"
SEASON_END_DATE = "2027-03-27T00:00:00Z"
SEASON_SLOT_RETURN_DEADLINE_UTC = "2026-09-15T23:59:59Z"
SEASON_FILING_CHANGE_WINDOW_CLOSE_UTC = "2026-10-11T23:59:59Z"

# Mondays inside the season window, used by the Monday slot series fixtures.
SEASON_MONDAYS = (
    "2026-11-02",
    "2026-11-09",
    "2026-11-16",
    "2026-11-23",
    "2026-11-30",
)
