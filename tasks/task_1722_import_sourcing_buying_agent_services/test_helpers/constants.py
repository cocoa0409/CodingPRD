"""Domain thresholds — numeric constants named in the PRD."""

# Logical clock startup default (PRD: "Its startup default before any such call
# is exactly 2026-08-01T00:00:00Z").
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Audit scoring (PRD audit-grading section)
CRITICAL_FINDING_DEDUCTION = 5
GRADE_A_MIN = 85
GRADE_B_MIN = 70
GRADE_C_MIN = 50

# Commission tiers (PRD commission section, step 1)
TIER1_MAX_CENTS = 10_000_000
TIER2_MAX_CENTS = 50_000_000
TIER1_RATE_BP = 500
TIER2_RATE_BP = 400
TIER3_RATE_BP = 300
CIF_CAP_RATE = 0.12

# Negotiation / sample caps
REVISION_CAP = 3
NEGOTIATION_ROUND_CAP = 6

# Milestone plan
PLAN_TOTAL_WEIGHT = 100

# Chargeback penalty tiers (PRD chargeback waterfall)
PENALTY_TIER1_MAX = 0.05
PENALTY_TIER2_MAX = 0.10
PENALTY_RATE_MID = 0.02
PENALTY_RATE_HIGH = 0.05
SUSPENSION_THRESHOLD_CENTS = 1_000_000

# Claim filing window (days after latest delivery)
CLAIM_WINDOW_DAYS = 30

# AQL 2.5 sampling: lot bounds (inclusive lower edge) -> (sample_size, Ac, Re)
AQL_PLAN = [
    (500, 50, 3, 4),      # lot_size <= 500
    (1200, 80, 5, 6),     # 501..1200
    (3200, 125, 7, 8),    # 1201..3200
    (None, 200, 10, 11),  # >= 3201
]

# Compliance doc types required per product category (PRD posture section)
REQUIRED_DOCS = {
    "APPAREL": ("SOCIAL_AUDIT", "PRODUCT_TEST"),
    "ELECTRONICS": ("PRODUCT_TEST", "LAB_TEST"),
    "TOYS": ("PRODUCT_TEST", "LAB_TEST", "SOCIAL_AUDIT"),
    "FURNITURE": ("FIRE_SAFETY", "PRODUCT_TEST"),
}

# Default temporal values used by fixtures (always valid at the default clock)
DEFAULT_VALID_UNTIL = "2027-01-01T00:00:00Z"
DEFAULT_DOC_EXPIRES_AT = "2027-06-01T00:00:00Z"
DEFAULT_DOC_ISSUED = "2026-01-01"
DEFAULT_DELIVERY_MONTH = "2026-09"
DEFAULT_INSPECTION_DATE = "2026-08-10"

# Standard audit inputs yielding an approved grade-A ONSITE audit
# (95/92/90/88 with 0 critical findings -> score 92 -> grade A).
GRADE_A_AUDIT = {
    "audit_type": "ONSITE",
    "quality_system_score": 95,
    "social_compliance_score": 92,
    "production_capability_score": 90,
    "financial_stability_score": 88,
    "critical_findings": 0,
}

TEST_DEFAULTS = {
    "UNIT_PRICE_CENTS": 100,
    "ORDERED_QTY": 10,
    "MONTHLY_CAPACITY_UNITS": 100000,
    "MOQ": 1,
    "LEAD_TIME_DAYS": 30,
}
