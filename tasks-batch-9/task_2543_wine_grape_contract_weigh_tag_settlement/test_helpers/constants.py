"""Domain thresholds and canonical harvest-calendar instants from the PRD.

Every numeric constant here is quoted from the PRD's business rules (quality
specification defaults, contract term defaults, lane defaults, prompt-payment
tiers, reliability weights).  The instants are the deterministic logical-clock
timeline the tests drive: the clock reads 2026-08-01T00:00:00Z before anything
moves it, and every test moves it explicitly.
"""

# --- The logical harvest clock -------------------------------------------------

CLOCK_INITIAL = "2026-08-01T00:00:00Z"

# Canonical harvest timeline (all UTC, all reached by explicit clock moves).
SAMPLING_WINDOW_START = "2026-08-20T06:00:00Z"
SAMPLING_WINDOW_END = "2026-08-20T10:00:00Z"
SAMPLING_RECORDED_AT = "2026-08-20T08:00:00Z"
PICK_CALL_ISSUED_AT = "2026-08-20T08:00:00Z"
PICK_CALL_ACK_DEADLINE_AT = "2026-08-21T08:00:00Z"
TARGET_PICK_AT = "2026-08-25T14:00:00Z"
APPOINTMENT_WINDOW_START = "2026-08-25T14:00:00Z"
APPOINTMENT_WINDOW_END = "2026-08-25T16:00:00Z"
TRUCK_ARRIVAL_AT = "2026-08-25T14:30:00Z"
GRADING_AT = "2026-08-25T14:30:00Z"
DISPUTE_DEADLINE_AT = "2026-08-28T14:30:00Z"
SETTLEMENT_CLOSE_AT = "2026-08-28T09:00:00Z"

SECONDS_PER_HOUR = 3600
POUNDS_PER_TON = 2000
ARRIVAL_GRACE_MINUTES = 60
DELIVERY_ENVELOPE_HOURS = 72
DISPUTE_WINDOW_HOURS = 72

# --- Quality specification: PRD-declared defaults -----------------------------
# "min_brix_pick_call ... defaults to 21.0; brix_step ... defaults to 0.5;
#  brix_bonus_pct_per_step defaults to 1.5 and brix_penalty_pct_per_step to 2.0"
QUALITY_SPEC_DEFAULTS = {
    "min_brix_pick_call": 21.0,
    "brix_step": 0.5,
    "brix_bonus_pct_per_step": 1.5,
    "brix_penalty_pct_per_step": 2.0,
    "ta_min_gl": 5.5,
    "ta_max_gl": 9.0,
    "acid_out_of_spec_penalty_pct": 3.0,
    "rot_free_pct": 2.0,
    "rot_penalty_pct_per_point": 1.5,
    "mog_max_pct": 1.0,
    "mog_penalty_pct": 2.5,
    "max_total_bonus_pct": 8.0,
    "max_total_penalty_pct": 20.0,
}

# The reference specification used across the suite supplies only the five
# mandatory thresholds, so every optional threshold takes its PRD default.
REFERENCE_SPEC = {
    "min_brix_accept": 20.0,
    "brix_penalty_start": 22.0,
    "brix_bonus_start": 24.0,
    "rot_rejection_pct": 8.0,
}

# --- Grape contract: PRD-declared defaults ------------------------------------
CONTRACT_DEFAULTS = {
    "spot_price_pct": 70.0,
    "over_delivery_tolerance_pct": 10.0,
    "settlement_basis": "LOAD_BY_LOAD",
    "provisional_payment_pct": 60.0,
    "lien_holdback_pct": 5.0,
    "min_pick_notice_hours": 48,
    "pick_call_ack_window_hours": 24,
    "evergreen_flag": False,
    "evergreen_term_years": 1,
    "termination_notice_days": 90,
}

# --- Crush-pad lane and sampling-crew defaults --------------------------------
LANE_DEFAULTS = {
    "turnaround_buffer_minutes": 30,
    "max_load_tons": 40.0,
    "status": "OPEN",
}
CREW_DEFAULTS = {"max_concurrent_visits": 2}

# --- Pagination ---------------------------------------------------------------
PAGINATION = {
    "default_limit": 10,
    "min_limit": 1,
    "max_limit": 100,
    "default_offset": 0,
}

# --- Prompt-payment tiers, keyed on the pre-credit settlement total -----------
PROMPT_PAY_TIERS = (
    (0, 5_000_000, 0.0),
    (5_000_000, 10_000_000, 0.5),
    (10_000_000, 15_000_000, 1.0),
    (15_000_000, None, 1.5),
)

# --- Producer reliability -----------------------------------------------------
RELIABILITY_WEIGHTS = {
    "rejected_load": 8,
    "expired_pick_call": 5,
    "no_show_appointment": 3,
}
RELIABILITY_START = 100.0
RENEWAL_RELIABILITY_THRESHOLD = 80.0

# --- Convenient test payload defaults -----------------------------------------
TEST_DEFAULTS = {
    "region_code": "NAPA-VALLEY",
    "ava_code": "NAPA-VALLEY",
    "varietal": "CABERNET_SAUVIGNON",
    "acres": 20.0,
    "expected_yield_tons_per_acre": 2.0,
    "base_price_per_ton_cents": 450_000,
    "committed_tons": 40.000,
    "daily_capacity_tons": 80.000,
    "term_start_vintage": 2026,
    "term_end_vintage": 2027,
}
