"""Domain thresholds — numeric constants from the PRD's calculations."""

# Signup / renewal pricing (PRD §3.2, §3.3)
ATTORNEY_ADDON_CENTS = 15000
BUNDLE_MULTIPLIER = {"INDIVIDUAL": 1.0, "COUPLE": 1.6}
STANDARD_BASE_PRICES = {"BASIC": 10000, "PLUS": 20000, "PREMIER": 35000}

# Loyalty discount tiers on renewal settlement (PRD §3.3)
LOYALTY_TIER_1_2_PCT = 0.10
LOYALTY_TIER_3_PLUS_PCT = 0.20

# Coverage window / renewal windows (PRD §2.5, §3.2, §3.3)
TERM_DAYS = 365
RENEWAL_WINDOW_DAYS = 30
GRACE_DAYS = 30

# Witness requirement (PRD §3.6)
WITNESS_BASE = {"WILL": 2, "TRUST": 0, "POA": 1, "HEALTHCARE_DIRECTIVE": 1}
WITNESS_SURCHARGE_STATES = {"LA", "VT"}

# Questionnaire required-field counts (PRD §3.5)
REQUIRED_FIELDS = {"WILL": 5, "TRUST": 7, "POA": 4, "HEALTHCARE_DIRECTIVE": 4}

# Allocation cap for non-contingent beneficiaries (PRD §3.9)
ALLOCATION_CAP_PCT = 100.00

# Server startup default logical clock (PRD §2.5)
DEFAULT_CLOCK = "2026-03-01T00:00:00Z"
