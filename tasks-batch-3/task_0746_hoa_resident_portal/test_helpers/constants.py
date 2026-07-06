"""Domain thresholds — numeric constants from PRD business logic."""

# Standing thresholds (dollars, from PRD §2.6 and §3.2)
STANDING_MARGINAL_MIN = 500
STANDING_DELINQUENT_MIN = 1500

# Late-fee tier boundaries (days_overdue thresholds — PRD §3.2)
TIER_2_START_DAYS = 14
TIER_3_START_DAYS = 30
TIER_4_START_DAYS = 60

# Tier rates (fraction of outstanding)
RATE_TIER_1 = 0.02
RATE_TIER_2 = 0.05
RATE_TIER_3 = 0.10
RATE_TIER_4 = 0.15

# Tier floors (cents)
FLOOR_TIER_1 = 1000
FLOOR_TIER_2 = 1000
FLOOR_TIER_3 = 2500
FLOOR_TIER_4 = 5000

# Tier caps (cents)
CAP_TIER_1 = 2500
CAP_TIER_2 = 5000
CAP_TIER_3 = 10000
CAP_TIER_4 = 25000

# Standing multipliers
STANDING_MULT_GOOD = 1.0
STANDING_MULT_MARGINAL = 1.5
STANDING_MULT_DELINQUENT = 2.0

# ARC base fees (cents, PRD §3.4)
ARC_BASE_SIMPLE_CENTS = 2500
ARC_BASE_MEDIUM_CENTS = 10000
ARC_BASE_COMPLEX_CENTS = 25000
ARC_REVIEW_RATE = 0.10725

# Delinquency-score grace window (days)
DELINQUENCY_GRACE_WINDOW_DAYS = 30

# Violation fine range (cents, PRD §3.5)
VIOLATION_FINE_MIN_CENTS = 2500
VIOLATION_FINE_MAX_CENTS = 500000

# Violation appeal window (days)
APPEAL_WINDOW_DAYS = 14

# Overdue → Delinquent, Delinquent → lien-eligible (days past due_date)
DELINQUENT_TRANSITION_DAYS = 60
LIEN_ELIGIBLE_DAYS = 90

# ARC revision limit
ARC_REVISION_LIMIT = 3

# Amenity reservation cap (hours)
AMENITY_MAX_HOURS = 8

# Motion category-overlap buffer (hours)
MOTION_BUFFER_HOURS = 24

# Server-boot default clock (PRD §2.9 / §3.9)
SERVER_DEFAULT_CLOCK = "2026-03-01T00:00:00Z"

# Pagination defaults (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
