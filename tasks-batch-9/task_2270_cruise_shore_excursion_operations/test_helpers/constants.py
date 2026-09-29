"""Numeric constants and canonical instants taken from the PRD's calculations.

Nothing here is invented: every figure is quoted in the PRD prose.
"""

# --------------------------------------------------------------------------
# The logical clock
# --------------------------------------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Canonical shared world instants used by the composite setups.
INSTANTS = {
    "CLOCK_BASE": "2026-08-01T00:00:00Z",
    "CALL_ARRIVAL": "2026-09-15T08:00:00Z",
    "CALL_ALL_ABOARD": "2026-09-15T16:30:00Z",
    "CALL_DEPARTURE": "2026-09-15T17:00:00Z",
    "MEETING_TIME": "2026-09-15T09:00:00Z",
    "WAVE1_START": "2026-09-15T08:30:00Z",
    "WAVE1_END": "2026-09-15T08:50:00Z",
    # Past the call's effective arrival and inside the inclusive check-in window
    # that runs from 45 minutes before the 09:00Z meeting time to 10 minutes
    # after it.
    "CHECKIN_CLOCK": "2026-09-15T08:30:00Z",
    "AUDIT_CONDUCTED_ON": "2026-07-20T00:00:00Z",
    "INSURANCE_EXPIRY": "2027-06-30T00:00:00Z",
}

# --------------------------------------------------------------------------
# Pricing (PRD §3.5 — five pinned steps)
# --------------------------------------------------------------------------
TIER_MULTIPLIER_BPS = {
    "VALUE": 9000,
    "STANDARD": 10000,
    "PREMIUM": 11500,
    "SIGNATURE": 13000,
}
ONBOARD_ADJUSTMENT_BPS = 800
PRECRUISE_EARLY_REDUCTION_BPS = 500
PRECRUISE_EARLY_DAYS = 7
LOYALTY_DISCOUNT_BPS = {"NONE": 0, "SILVER": 250, "GOLD": 500, "PLATINUM": 800}
GROUP_DISCOUNT_BPS = {"SIX_PLUS": 1000, "FOUR_OR_FIVE": 500, "BELOW_FOUR": 0}
DISCOUNT_CAP_BPS = 1200
SERVICE_FEE_BPS = 300
SERVICE_FEE_CAP_CENTS = 1500

# --------------------------------------------------------------------------
# Channels and seat release (PRD §3.5)
# --------------------------------------------------------------------------
PRECRUISE_RELEASE_MINUTES = 2880

# --------------------------------------------------------------------------
# Guest-initiated refund tiers (PRD §3.7), minutes-to-meeting -> bps
# --------------------------------------------------------------------------
REFUND_TIER_FULL_MINUTES = 4320       # >= 4320 -> 10000 bps including service fee
REFUND_TIER_THREE_QUARTER_MINUTES = 1440   # >= 1440 -> 7500 bps of quoted_total
REFUND_TIER_HALF_MINUTES = 180        # >= 180 -> 5000 bps of quoted_total
REFUND_TIER_BPS = {
    "FULL": 10000,
    "THREE_QUARTER": 7500,
    "HALF": 5000,
    "NONE": 0,
}

# --------------------------------------------------------------------------
# Timing risk (PRD §3.4)
# --------------------------------------------------------------------------
TRANSFER_BUFFER_MINUTES = 30              # 15 minutes at each end
UNASSIGNED_WAVE_PENALTY_MINUTES = 20
AMBER_MAX_SLACK_MINUTES = 45              # slack > 45 -> GREEN
RED_MAX_SLACK_MINUTES = 0                 # slack <= 0 -> RED
MEETING_POINT_SETUP_MINUTES = 15

# --------------------------------------------------------------------------
# Sales, check-in and dispatch deadlines (PRD §2.8, §3.4, §3.6)
# --------------------------------------------------------------------------
SALES_CUTOFF_MINUTES = 60
CHECKIN_WINDOW_BEFORE_MINUTES = 45
CHECKIN_WINDOW_AFTER_MINUTES = 10
ALTERNATIVE_MIN_LEAD_MINUTES = 15

# --------------------------------------------------------------------------
# Operator standing (PRD §3.2)
# --------------------------------------------------------------------------
AUDIT_WINDOW_SIZE = 3
AUDIT_BASE_WEIGHTS = [0.5, 0.3, 0.2]
CRITICAL_FINDING_PENALTY_POINTS = 8
UPHELD_CLAIM_PENALTY_POINTS = 5
SAFETY_SCORE_FLOOR = 60
SAFETY_SCORE_MIN = 0
SAFETY_SCORE_MAX = 100
INSURANCE_LIMIT_MINIMUM_CENTS = 100_000_000
PUBLICATION_INSURANCE_RUNWAY_DAYS = 30
MAX_VETTING_CYCLE_COUNT = 3
RELIABILITY_STRIKES_TO_SUSPEND = 3

# --------------------------------------------------------------------------
# Eligibility screening (PRD §3.5)
# --------------------------------------------------------------------------
GUEST_MOBILITY_RANK = {"WHEELCHAIR": 1, "ASSISTED": 2, "FULL": 3}
EXCURSION_REQUIRED_RANK = {"LEVEL_1": 1, "LEVEL_2": 2, "LEVEL_3": 3, "LEVEL_4": 3}
LEVEL_4_EXCLUDED_MEDICAL_FLAGS = ["CARDIAC", "RESPIRATORY", "PREGNANCY"]

# --------------------------------------------------------------------------
# Cancellation money (PRD §3.6, §3.7)
# --------------------------------------------------------------------------
GOODWILL_CREDIT_BPS = 1000
OPERATIONAL_PENALTY_BPS = 2000
REPATRIATION_ALLOWANCE_CENTS = 25_000
RETURN_GUARANTEE_REFUND_BPS = 10_000

# --------------------------------------------------------------------------
# Commission and settlement (PRD §3.9)
# --------------------------------------------------------------------------
NO_SHOW_COMMISSION_FLOOR_BPS = 500
PORT_FEE_BPS = 250
REBATE_TIER_HIGH_THRESHOLD_CENTS = 500_000
REBATE_TIER_HIGH_BPS = 150
REBATE_TIER_MID_THRESHOLD_CENTS = 200_000
REBATE_TIER_MID_BPS = 75
REBATE_TIER_LOW_BPS = 0

# --------------------------------------------------------------------------
# Claims (PRD §3.8)
# --------------------------------------------------------------------------
MAX_DISPUTE_ROUNDS = 2
LIABILITY_SHARE_MIN_BPS = 1
LIABILITY_SHARE_MAX_BPS = 10_000

# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0

# --------------------------------------------------------------------------
# Field ranges declared in the PRD
# --------------------------------------------------------------------------
RANGES = {
    "risk_buffer_minutes": (0, 240),
    "tender_egress_minutes": (0, 180),
    "max_concurrent_groups": (1, 12),
    "slot_buffer_minutes": (0, 60),
    "wave_index": (1, 40),
    "commission_rate_bps": (0, 5000),
    "raw_score": (0, 100),
    "critical_finding_count": (0, 20),
    "duration_minutes": (30, 720),
    "min_age": (0, 21),
    "max_age": (0, 120),
    "dispatch_dwell_minutes": (5, 120),
    "total_capacity": (1, 500),
    "party_size": (1, 20),
}
