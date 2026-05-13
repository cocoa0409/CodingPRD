"""Domain thresholds and stable defaults derived from PRD prose for the IP
Management API.

Every named constant traces to a PRD sentence — the in-line comment cites the
prose it transcribes.
"""

# ─────────────── Annual-fee surcharge tiers (PRD §3.3) ───────────────
# "When `days_late` is at most zero the `surcharge_rate` is zero."
# "When `days_late` falls in the range from 1 to 30 inclusive ... the rate is 0.10."
# "When `days_late` falls in the range from 31 to 90 inclusive ..., the rate is 0.25."
# "When `days_late` falls in the range from 91 to 180 inclusive ..., the rate is 0.50."
SURCHARGE = {
    "TIER_1_MAX_DAYS": 30,
    "TIER_2_MAX_DAYS": 90,
    "GRACE_MAX_DAYS": 180,
    "TIER_0_RATE": 0.00,
    "TIER_1_RATE": 0.10,
    "TIER_2_RATE": 0.25,
    "TIER_3_RATE": 0.50,
}

# ─────────────── Agent workload weights (PRD §3.1) ───────────────────
# "multiplying `active_case_count` by 0.40, `pending_action_count` by 0.30,
#  `upcoming_deadline_count` by 0.30 ..."
WORKLOAD_WEIGHTS = {
    "ACTIVE_CASE": 0.40,
    "PENDING_ACTION": 0.30,
    "UPCOMING_DEADLINE": 0.30,
}

# ─────────────── Performance-rating scores (PRD §3.1) ────────────────
# "5.0 for `WON`, 3.5 for `SETTLED`, 2.0 for `DISMISSED`, 1.0 for `LOST`"
PERFORMANCE_SCORES = {
    "WON": 5.0,
    "SETTLED": 3.5,
    "DISMISSED": 2.0,
    "LOST": 1.0,
}
# "take the first ten of that ordering (use all of them if fewer than ten exist)"
PERFORMANCE_WINDOW_SIZE = 10

# ─────────────── Allocation basis-points (PRD §3.7) ───────────────────
# "the entries' `percent_bps` values must sum to exactly 10000"
BPS_TOTAL = 10000

# ─────────────── Pagination (PRD §2.3) ─────────────────────────────
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# ─────────────── Day-in-seconds helper for /_clock/advance ────────────
SECONDS_PER_DAY = 86400

# ─────────────── Generic stable defaults used by factories ───────────
TEST_DEFAULTS = {
    "BU_BUDGET_LARGE": 10_000_000_00,   # 10 billion cents, ample headroom
    "BU_BUDGET_TIGHT": 10_000,          # ~$100 — used to provoke ERR_BUDGET_EXCEEDED
    "AGENT_HOURLY_RATE": 50_000,        # $500/hour
    "BASE_FEE_DEFAULT": 100_000,        # $1000.00 — anchors the surcharge tests
    "RIGHTS_HOLDER_CURRENCY": "USD",
    "PRIMARY_JURISDICTION": "US",
}

# ─────────────── Days-from-due_date helpers (PRD §3.3) ────────────────
# "grace_end_date ... due_date plus exactly 180 days"
GRACE_DAYS = 180
