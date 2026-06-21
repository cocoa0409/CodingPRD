"""Domain thresholds — numeric constants from the PRD pricing rules.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Service-visit truck-roll fee (PRD §3.8): SERVICE completion and any no-show.
SERVICE_TRUCK_ROLL_CENTS = 9900

# Early-termination-fee tenure-breakpoint schedule (PRD §3.8).
ETF_MAX_CENTS = 24000        # remaining >= 12 months
ETF_MID_CENTS = 15000        # 6 <= remaining < 12 months
ETF_MIN_CENTS = 2000         # floor for 1 <= remaining < 6 months
ETF_PER_MONTH_CENTS = 1500   # per remaining month in the low tier

# Top package rank that triggers the regional-sports-fee premier surcharge.
PREMIER_RANK = 3

# Account-level visit buffer (PRD §3.9): minimum gap in minutes between visits.
ACCOUNT_VISIT_BUFFER_MIN = 60

THRESHOLDS = {
    "SERVICE_TRUCK_ROLL_CENTS": SERVICE_TRUCK_ROLL_CENTS,
    "ETF_MAX_CENTS": ETF_MAX_CENTS,
    "ETF_MID_CENTS": ETF_MID_CENTS,
    "ETF_MIN_CENTS": ETF_MIN_CENTS,
    "ETF_PER_MONTH_CENTS": ETF_PER_MONTH_CENTS,
    "PREMIER_RANK": PREMIER_RANK,
    "ACCOUNT_VISIT_BUFFER_MIN": ACCOUNT_VISIT_BUFFER_MIN,
}
