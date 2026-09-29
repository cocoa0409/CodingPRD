"""Domain constants for the writers-room staffing and script development API.

Holds the canonical guild-agreement rate card used by the fixture ladder, the
logical-clock landmarks, and the pre-computed money/date figures that the PRD
uniquely derives from that rate card.
"""

# --- Logical clock -----------------------------------------------------------

# Before any client sets it, the logical clock reads exactly this instant.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

CLOCK_MID_STAFFING = "2026-09-05T00:00:00Z"
CLOCK_AFTER_STAFFING_WINDOW = "2026-10-05T00:00:00Z"
CLOCK_LATE_OUTLINE = "2026-09-25T00:00:00Z"
CLOCK_AFTER_FIRST_DRAFT = "2026-10-08T00:00:00Z"

# --- Enum vocabularies -------------------------------------------------------

LEVEL_ORDER = [
    "STAFF_WRITER",
    "STORY_EDITOR",
    "EXEC_STORY_EDITOR",
    "CO_PRODUCER",
    "PRODUCER",
]

LENGTH_FORMATS = ["HALF_HOUR", "ONE_HOUR"]

ASSIGNMENT_TYPES = [
    "STORY",
    "TELEPLAY",
    "STORY_AND_TELEPLAY",
    "REWRITE",
    "PRODUCTION_POLISH",
]

ROOM_FORMATS = ["IN_PERSON", "REMOTE", "MINI_ROOM"]

COMMITMENT_TYPES = ["EXCLUSIVE", "NON_EXCLUSIVE"]

CLEARANCE_ITEM_TYPES = ["NAME", "TRADEMARK", "DEPICTION"]

CLAIM_BASES = ["WRITTEN_BY", "STORY_BY", "TELEPLAY_BY"]

LEDGER_ENTRY_TYPES = [
    "SCRIPT_FEE_ACCRUAL",
    "GUARANTEE_OFFSET",
    "GUARANTEE_REALLOCATION",
    "FEE_REVERSAL",
]

PRODUCTION_UNITS = ["UNIT_A", "UNIT_B"]

# --- Canonical guild agreement (rate card) ----------------------------------

MIN_WEEKLY_CENTS_BY_LEVEL = {
    "STAFF_WRITER": 450000,
    "STORY_EDITOR": 600000,
    "EXEC_STORY_EDITOR": 700000,
    "CO_PRODUCER": 850000,
    "PRODUCER": 1000000,
}

SCRIPT_FEE_CENTS_BY_LENGTH = {
    "HALF_HOUR": 2500000,
    "ONE_HOUR": 5000000,
}

TYPE_SHARE_PCT_BY_ASSIGNMENT_TYPE = {
    "STORY": 0.30,
    "TELEPLAY": 0.70,
    "STORY_AND_TELEPLAY": 1.00,
    "REWRITE": 0.35,
    "PRODUCTION_POLISH": 0.175,
}

GUARANTEE_OFFSET_PCT_BY_LEVEL = {
    "STAFF_WRITER": 0.0,
    "STORY_EDITOR": 0.5,
    "EXEC_STORY_EDITOR": 0.5,
    "CO_PRODUCER": 1.0,
    "PRODUCER": 1.0,
}

LEVEL_CREDIT_THRESHOLDS = {
    "STORY_EDITOR": 2,
    "EXEC_STORY_EDITOR": 4,
    "CO_PRODUCER": 7,
    "PRODUCER": 12,
}

FACILITY_FEE_TIERS = {"TIER_1": 200000, "TIER_2": 350000, "TIER_3": 500000}
FACILITY_TIER_SUBTOTAL_BOUNDS = {"TIER_1_MAX": 1500000, "TIER_2_MAX": 3000000}
FORMAT_SURCHARGE_PCT = {"IN_PERSON": 1.0, "REMOTE": 0.4, "MINI_ROOM": 0.6}
CLEARANCE_ITEM_WEIGHTS = {"NAME": 5, "TRADEMARK": 15, "DEPICTION": 25}

DIVERSITY_SUBSIDY_PCT = 0.5
DIVERSITY_SUBSIDY_CAP_WEEKLY_CENTS = 250000
MINI_ROOM_FLOOR_MULTIPLIER = 1.2
SHORT_COMMITMENT_WEEKS_THRESHOLD = 20
SHORT_COMMITMENT_UPLIFT_PCT = 0.1
MAX_FREE_REVISION_ROUNDS = 2
CREDIT_SHARE_THRESHOLD_PCT = 33
ARBITRATION_CONCURRENCE_PCT = 0.667
ARBITRATION_CONCURRENCE_BAND_PCT = 10
OUTLINE_LEAD_DAYS = 42
FIRST_DRAFT_LEAD_DAYS = 28
SECOND_DRAFT_LEAD_DAYS = 14
POLISH_LEAD_DAYS = 3
TURNAROUND_BUFFER_DAYS = 2
CLEARANCE_ESCALATION_SCORE = 30

BASE_AGREEMENT = {
    "mba_year": 2026,
    "min_weekly_cents_by_level": MIN_WEEKLY_CENTS_BY_LEVEL,
    "script_fee_cents_by_length": SCRIPT_FEE_CENTS_BY_LENGTH,
    "type_share_pct_by_assignment_type": TYPE_SHARE_PCT_BY_ASSIGNMENT_TYPE,
    "guarantee_offset_pct_by_level": GUARANTEE_OFFSET_PCT_BY_LEVEL,
    "level_credit_thresholds": LEVEL_CREDIT_THRESHOLDS,
    "diversity_subsidy_pct": DIVERSITY_SUBSIDY_PCT,
    "diversity_subsidy_cap_weekly_cents": DIVERSITY_SUBSIDY_CAP_WEEKLY_CENTS,
    "mini_room_floor_multiplier": MINI_ROOM_FLOOR_MULTIPLIER,
    "short_commitment_weeks_threshold": SHORT_COMMITMENT_WEEKS_THRESHOLD,
    "short_commitment_uplift_pct": SHORT_COMMITMENT_UPLIFT_PCT,
    "facility_fee_tiers": FACILITY_FEE_TIERS,
    "facility_tier_subtotal_bounds": FACILITY_TIER_SUBTOTAL_BOUNDS,
    "format_surcharge_pct": FORMAT_SURCHARGE_PCT,
    "max_free_revision_rounds": MAX_FREE_REVISION_ROUNDS,
    "credit_share_threshold_pct": CREDIT_SHARE_THRESHOLD_PCT,
    "arbitration_concurrence_pct": ARBITRATION_CONCURRENCE_PCT,
    "arbitration_concurrence_band_pct": ARBITRATION_CONCURRENCE_BAND_PCT,
    "outline_lead_days": OUTLINE_LEAD_DAYS,
    "first_draft_lead_days": FIRST_DRAFT_LEAD_DAYS,
    "second_draft_lead_days": SECOND_DRAFT_LEAD_DAYS,
    "polish_lead_days": POLISH_LEAD_DAYS,
    "turnaround_buffer_days": TURNAROUND_BUFFER_DAYS,
    "clearance_item_weights": CLEARANCE_ITEM_WEIGHTS,
    "clearance_escalation_score": CLEARANCE_ESCALATION_SCORE,
}

# The required-only projection of the agreement payload: every optional field
# omitted so the server has to supply its declared default.
REQUIRED_ONLY_AGREEMENT_KEYS = [
    "mba_year",
    "min_weekly_cents_by_level",
    "script_fee_cents_by_length",
    "type_share_pct_by_assignment_type",
    "guarantee_offset_pct_by_level",
    "level_credit_thresholds",
    "diversity_subsidy_cap_weekly_cents",
    "facility_fee_tiers",
    "facility_tier_subtotal_bounds",
    "format_surcharge_pct",
    "outline_lead_days",
    "first_draft_lead_days",
    "second_draft_lead_days",
    "polish_lead_days",
    "clearance_item_weights",
]

# --- Season / room / seat landmarks -----------------------------------------

# Every date-valued input field is a full ISO 8601 instant on the wire.
SEASON_PRODUCTION_START = "2026-11-02T00:00:00Z"
STAFFING_WINDOW_START = "2026-08-01T00:00:00Z"
STAFFING_WINDOW_END = "2026-09-30T00:00:00Z"

ROOM_START_DATE = "2026-09-01T00:00:00Z"
ROOM_END_DATE = "2027-03-01T00:00:00Z"
WINDOW_START_DATE = "2026-08-15T00:00:00Z"
WINDOW_END_DATE = "2027-06-01T00:00:00Z"


def at_midnight(calendar_date: str) -> str:
    """Return the bare calendar date `calendar_date` as a full ISO 8601 instant."""
    return f"{calendar_date[:10]}T00:00:00Z"

# --- Pre-computed derived figures -------------------------------------------

# script_fee_derivation: ONE_HOUR base 5,000,000 cents.
SCRIPT_FEE_ONE_HOUR = {
    "STORY": 1500000,
    "TELEPLAY": 3500000,
    "STORY_AND_TELEPLAY": 5000000,
    "REWRITE": 1750000,
    "PRODUCTION_POLISH": 875000,
}
# HALF_HOUR base 2,500,000 cents.
SCRIPT_FEE_HALF_HOUR = {
    "STORY": 750000,
    "TELEPLAY": 1750000,
    "STORY_AND_TELEPLAY": 2500000,
    "REWRITE": 875000,
    "PRODUCTION_POLISH": 437500,
}

# milestone_schedule_derivation against production_start_date 2026-11-02.
DUE_DATES_NOV_02 = {
    "OUTLINE": "2026-09-21T23:59:59.999Z",
    "FIRST_DRAFT": "2026-10-05T23:59:59.999Z",
    "SECOND_DRAFT": "2026-10-19T23:59:59.999Z",
    "POLISH": "2026-10-30T23:59:59.999Z",
}
# ... and against the rescheduled production_start_date 2027-01-04.
DUE_DATES_JAN_04 = {
    "OUTLINE": "2026-11-23T23:59:59.999Z",
    "FIRST_DRAFT": "2026-12-07T23:59:59.999Z",
    "SECOND_DRAFT": "2026-12-21T23:59:59.999Z",
    "POLISH": "2027-01-01T23:59:59.999Z",
}
RESCHEDULED_PRODUCTION_START = "2027-01-04T00:00:00Z"

# seat_prorated_commitment for the canonical 2026-09-01 -> 2027-03-01 seat at
# 600,000 cents per week: 181 days = 25 whole weeks plus 6 residual days.
SEAT_PRORATED_181_DAYS_AT_600000 = 15514284
SEAT_DAYS_181 = 181

# The pinned rounding order for a 17-day commitment at 450,000 cents per week.
SEAT_PRORATED_17_DAYS_AT_450000 = 1092858

# room_weekly_burn landmarks for the canonical IN_PERSON room.
ROOM_BURN_EMPTY_IN_PERSON = 200000
ROOM_BURN_ONE_SEAT_600000 = 800000
ROOM_BURN_EMPTY_REMOTE = 80000
FACILITY_TIER_1 = "TIER_1"
FACILITY_TIER_2 = "TIER_2"
FACILITY_TIER_3 = "TIER_3"
