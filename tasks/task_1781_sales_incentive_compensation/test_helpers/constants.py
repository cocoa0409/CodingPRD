"""Domain thresholds and canonical inputs — numeric constants from the PRD.

The canonical three-tier quota-to-payout curve used by most scenarios:
  [{floor 0, rate 1000}, {floor 8000, rate 1500}, {floor 10000, rate 2500}]
with quota 1,000,000 cents puts the band edges at 0 / 800,000 / 1,000,000
cents. A flat 10% curve is used where the curve shape is irrelevant.
"""

TOTAL_BPS = 10000  # 10000 basis points is exactly 100 percent (PRD §2.6)

CANONICAL_CURVE_TIERS = [
    {"attainment_floor_bps": 0, "rate_bps": 1000},
    {"attainment_floor_bps": 8000, "rate_bps": 1500},
    {"attainment_floor_bps": 10000, "rate_bps": 2500},
]

FLAT_CURVE_TIERS = [
    {"attainment_floor_bps": 0, "rate_bps": 1000},
]

DEFAULT_QUOTA_CENTS = 1_000_000

DEFAULT_PLAN_START = "2026-01-01"
DEFAULT_PLAN_END = "2026-12-31"
DEFAULT_TRANSACTION_DATE = "2026-02-01"

# Operator identities. Segregation of duties (PRD §2.8) requires the plan
# publisher/reviser to differ from the plan creator, and the adjustment
# approver to differ from the adjustment creator.
PLAN_CREATOR_USER_ID = "admin-1"
PLAN_PUBLISHER_USER_ID = "admin-2"
ANALYST_USER_ID = "ops-1"
MANAGER_USER_ID = "mgr-1"

# Effectiveness distribution bucket bounds (PRD §3.9).
BUCKET_MID_BPS = 8000
BUCKET_HIGH_BPS = 10000

# Dispute filing window depth (PRD §3.6): no earlier than two periods back.
DISPUTE_WINDOW_DEPTH = 2
