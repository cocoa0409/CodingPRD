"""Domain thresholds — numeric constants from the PRD's pricing and capacity rules.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Pricing engine constants (PRD §3.6).
MULTI_WEEK_THRESHOLD = 2          # week_count at/above which the camp discount applies
MULTI_WEEK_DISCOUNT_PCT = 0.10    # ten percent multi-week camp discount
SIBLING_DISCOUNT_PCT = 0.15       # fifteen percent 2nd+ sibling discount

# Capacity posture (PRD §2.6).
RESTRICTED_FRACTION = 0.8         # restricted threshold = ceil(effective_capacity * 0.8)

# Member progress score weights (PRD §3.7).
W_BELT = 0.5
W_BADGE = 0.3
W_ATTEND = 0.2

# Showcase-session clash buffer (PRD §3.8): symmetric closed window in minutes.
SHOWCASE_BUFFER_MINUTES = 120

# The logical clock startup default (PRD §2.5).
CLOCK_DEFAULT = "2026-04-01T00:00:00Z"

THRESHOLDS = {
    "MULTI_WEEK_THRESHOLD": MULTI_WEEK_THRESHOLD,
    "MULTI_WEEK_DISCOUNT_PCT": MULTI_WEEK_DISCOUNT_PCT,
    "SIBLING_DISCOUNT_PCT": SIBLING_DISCOUNT_PCT,
    "RESTRICTED_FRACTION": RESTRICTED_FRACTION,
    "W_BELT": W_BELT,
    "W_BADGE": W_BADGE,
    "W_ATTEND": W_ATTEND,
    "SHOWCASE_BUFFER_MINUTES": SHOWCASE_BUFFER_MINUTES,
}
