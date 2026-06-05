"""Domain thresholds — numeric constants from PRD calculations (§2 / §3).

Generic NON_EXISTENT_UUID comes from the framework, re-exported via the barrel.
"""

# §3.5 / §3.6 self-pay and parity factors.
SELF_PAY_DISCOUNT_FACTOR = 0.80          # self-pay discount factor (an 80% rate)
NON_PARITY_PLAN_SHARE = 0.50             # non-parity plan share (half of allowed)

# §3.7 DEA exam recency window.
DEA_EXAM_RECENCY_DAYS = 180              # boundary day (delta == 180) still satisfies

# §3.2 visit slot buffer.
VISIT_BUFFER_MINUTES = 30                # exclusive boundary

# §3.8 follow-up interval.
FOLLOW_UP_INTERVAL_DAYS = 30

# §2.3 pagination bounds.
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100

THRESHOLDS = {
    "SELF_PAY_DISCOUNT_FACTOR": SELF_PAY_DISCOUNT_FACTOR,
    "NON_PARITY_PLAN_SHARE": NON_PARITY_PLAN_SHARE,
    "DEA_EXAM_RECENCY_DAYS": DEA_EXAM_RECENCY_DAYS,
    "VISIT_BUFFER_MINUTES": VISIT_BUFFER_MINUTES,
    "FOLLOW_UP_INTERVAL_DAYS": FOLLOW_UP_INTERVAL_DAYS,
}
