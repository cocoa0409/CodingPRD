"""Domain thresholds — numeric constants from the PRD's pricing and grading rules.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Provisional flat accessorial reserve folded into the quoted freight cost (§3.5).
ACCESSORIAL_ESTIMATE_CENTS = 5000

# Audit-time accessorial pricing (§3.10).
DETENTION_CENTS = 7500
LIFTGATE_CENTS = 3500
RESIDENTIAL_CENTS = 2500
REWEIGH_LIGHT_CENTS = 1500     # weight < 5000
REWEIGH_MID_CENTS = 4000       # 5000 <= weight < 20000
REWEIGH_HEAVY_CENTS = 9000     # weight >= 20000
REWEIGH_MID_LB = 5000          # inclusive lower boundary of MID tier
REWEIGH_HEAVY_LB = 20000       # inclusive lower boundary of HEAVY tier

# Carrier scorecard grade thresholds (§3.1). Boundaries are inclusive (>=).
GRADE_A_ONTIME = 95
GRADE_A_CLAIM_MAX = 0.02
GRADE_B_ONTIME = 90
GRADE_B_CLAIM_MAX = 0.05
GRADE_C_ONTIME = 80

# Freight-invoice approval tolerance (§3.11): abs(variance) must be <= this.
TOLERANCE_CENTS = 500

# A syntactically valid UUID that is guaranteed not to resolve to any entity.
MISSING_UUID = "00000000-0000-4000-8000-000000000000"
