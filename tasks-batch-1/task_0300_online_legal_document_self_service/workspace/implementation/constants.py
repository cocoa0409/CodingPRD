"""Fixed vocabularies and calculation constants (SCAFFOLD §1.3, PRD §3)."""

STATE_CODES = {"CA", "NY", "TX", "FL"}
DOCUMENT_TYPES = {"WILL", "LLC", "POA", "LEASE"}
TIERS = {"FREE", "STANDARD", "PREMIUM"}

# provisional_pricing / final_pricing document portion
BASE_PRICE_CENTS = {"WILL": 4999, "LLC": 9999, "POA": 3999, "LEASE": 2999}
STATE_SURCHARGE_CENTS = {"CA": 1500, "NY": 1999, "TX": 0, "FL": 0}
EXTRA_CLAUSE_FEE_CENTS = 799

# review_pricing
REVIEW_SURCHARGE_CENTS = 7500

# final_pricing notary line
NOTARY_FEE_CENTS = 2500

# project_completeness denominators (provisional)
TOTAL_REQUIRED_QUESTIONS = {"WILL": 8, "LLC": 6, "POA": 4, "LEASE": 6}

# UpdateReminder scheduling
REMINDER_INTERVAL_DAYS = 90

# Lease term turnover gap
LEASE_TURNOVER_BUFFER_DAYS = 7
