"""Domain thresholds — numeric constants from PRD calculations."""

# Sliding fee scale (PRD §2.10)
FPL_BASE = 15060
FPL_PER_ADDL = 5380

# Standard CPT rates in cents (PRD §2.11 / §3.6)
STD_RATE_90791_CENTS = 22000
STD_RATE_90834_CENTS = 15000

# Credential promotion thresholds (PRD §3.3)
ASSOCIATE_TO_SUPERVISED_HOURS = 1500
INDEPENDENT_HOURS = 3000
SUPERVISION_RATIO = 20

# Crisis risk score weights and band thresholds (PRD §3.8)
W_IDEATION = 0.30
W_PLAN = 0.30
W_MEANS = 0.25
W_PRIOR = 0.15
HIGH_THRESHOLD = 70
MODERATE_THRESHOLD = 40

MINUTES_PER_HOUR = 60

# Default injected hour totals that make a therapist INDEPENDENT-eligible.
INJECT_DIRECT_HOURS = 3000
INJECT_SUPERVISION_HOURS = 200
