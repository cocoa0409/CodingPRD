"""Domain thresholds — numeric constants from the PRD's pricing and policy rules.

Generic NON_EXISTENT_UUID comes from the framework. A fixed, well-formed UUID
that resolves to no resource is provided here for not-found / FK tests that need
a deterministic string.
"""

# Rush surcharge tiers (PRD §3.5 "Rush surcharge").
RUSH_TIER1_CAP = 5000          # cents; tier-1 portion is [0, 5000)
RUSH_TIER2_CAP = 20000         # cents; tier-2 portion is [5000, 20000)
RUSH_RATE_1 = 0.30
RUSH_RATE_2 = 0.20
RUSH_RATE_3 = 0.10
RUSH_FLOOR_CENTS = 1500        # minimum applied surcharge for any RUSH ticket

# Parts markup multipliers (PRD §3.5 "Parts markup").
MARKUP_MULTIPLIER = 1.35       # retail markup on a normal ticket
AT_COST_MULTIPLIER = 1.0       # warranty-redo ticket: parts passed at wholesale

# Ready-by SLA (PRD §3.5 "Ready-by SLA").
RUSH_SLA_FACTOR = 0.5
RUSH_MIN_DAYS = 1

# Unclaimed / disposal windows, whole calendar days from ready_at (PRD §3.7).
UNCLAIMED_GRACE_DAYS = 30
DISPOSAL_DAYS = 90

THRESHOLDS = {
    "RUSH_TIER1_CAP": RUSH_TIER1_CAP,
    "RUSH_TIER2_CAP": RUSH_TIER2_CAP,
    "RUSH_RATE_1": RUSH_RATE_1,
    "RUSH_RATE_2": RUSH_RATE_2,
    "RUSH_RATE_3": RUSH_RATE_3,
    "RUSH_FLOOR_CENTS": RUSH_FLOOR_CENTS,
    "MARKUP_MULTIPLIER": MARKUP_MULTIPLIER,
    "AT_COST_MULTIPLIER": AT_COST_MULTIPLIER,
    "RUSH_SLA_FACTOR": RUSH_SLA_FACTOR,
    "RUSH_MIN_DAYS": RUSH_MIN_DAYS,
    "UNCLAIMED_GRACE_DAYS": UNCLAIMED_GRACE_DAYS,
    "DISPOSAL_DAYS": DISPOSAL_DAYS,
}

# A syntactically valid UUID that resolves to no resource (for not-found tests).
MISSING_UUID = "00000000-0000-4000-8000-0000000000aa"

# Default clock instant used across fixtures for deterministic temporal math.
BASE_CLOCK = "2026-03-01T09:00:00Z"
