"""Domain thresholds and numeric constants from the PRD.

These constants encode numeric values the PRD pins to calculations
(exam pass threshold, instructor-fee tier multipliers, evaluation
weights, credit shortfall triggers).
"""
from __future__ import annotations


# PRD §3.5 — exam pass boundary (inclusive on the pass side).
PASS_THRESHOLD = 70

# PRD §3.6 — instructor fee tier multipliers.
TIER_1_MAX = 2.0          # effective_hours in [0.5, 2.0] -> multiplier 1.00
TIER_2_MAX = 5.0          # effective_hours in (2.0, 5.0] -> multiplier 0.95
TIER_1_MULT = 1.00
TIER_2_MULT = 0.95
TIER_3_MULT = 0.90        # effective_hours > 5.0

# PRD §3.5 — evaluation aggregate weights.
W_CONTENT = 0.4
W_INSTRUCTOR = 0.3
W_LOGISTICS = 0.3

# PRD §2.11 — shortfall warning trigger thresholds.
TIME_TRIGGER = 0.25       # time_fraction_remaining <= 0.25 (inclusive)
CREDIT_TRIGGER = 0.5      # credit_fraction < 0.5 (strict)

# PRD §3.3 — session cancellation fee window.
CANCEL_FEE_HOURS = 48

# PRD §3.1 — category depth limit.
MAX_CATEGORY_DEPTH = 4

# PRD §3.1 — prerequisite cycle scan depth.
PREREQUISITE_CHAIN_LIMIT = 5

# PRD §3.5 — IP_RANGE check-in allowed CIDRs.
ALLOWED_IP_PREFIXES = ("10.", "192.168.")

# Sensible defaults a fixture may use when it does not need a fresh id
# per test.
TEST_DEFAULTS = {
    "DURATION_HOURS": 4.0,
    "CREDIT_VALUE": 4.0,
    "SESSION_CAPACITY": 10,
    "WAITLIST_CAPACITY": 5,
    "JOB_LEVEL": 5,
    "REQUIRED_CREDITS": 20.0,
    "INSTRUCTOR_HOURLY_RATE": 200.00,
    "INSTRUCTOR_TRAVEL_COST": 50.00,
    "CLASSROOM_CAPACITY": 30,
    "CLASSROOM_SETUP_BUFFER": 30,
    "ONLINE_ROOM_MAX_PARTICIPANTS": 100,
    "VALIDITY_MONTHS": 12,
    "RENEWAL_WINDOW_DAYS": 30,
    "DEPARTMENT": "engineering",
}


__all__ = [
    "PASS_THRESHOLD",
    "TIER_1_MAX",
    "TIER_2_MAX",
    "TIER_1_MULT",
    "TIER_2_MULT",
    "TIER_3_MULT",
    "W_CONTENT",
    "W_INSTRUCTOR",
    "W_LOGISTICS",
    "TIME_TRIGGER",
    "CREDIT_TRIGGER",
    "CANCEL_FEE_HOURS",
    "MAX_CATEGORY_DEPTH",
    "PREREQUISITE_CHAIN_LIMIT",
    "ALLOWED_IP_PREFIXES",
    "TEST_DEFAULTS",
]
