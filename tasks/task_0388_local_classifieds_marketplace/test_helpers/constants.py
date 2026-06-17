"""Domain thresholds — numeric constants stated in the PRD (Sections 2-3)."""

# Listing / negotiation / moderation thresholds (PRD Section 3).
MAX_ACTIVE_LISTINGS = 3           # §3.3 active-listing cap of 3
MAX_RENEWALS = 2                  # §3.3 renewal cap of 2
LISTING_TTL_DAYS = 30            # §3.3 listing time-to-live of 30 days
OFFER_TTL_HOURS = 48             # §3.5 offer time-to-live of 48 hours
MAX_NEGOTIATION_ROUNDS = 5       # §3.5 negotiation round cap of 5
SPAM_FLAG_THRESHOLD = 3          # §3.7 spam-flag threshold of 3
BAN_UPHELD_THRESHOLD = 2         # §3.1 ban threshold of 2
HIGH_VALUE_THRESHOLD = 50000     # §3.6 high-value threshold of 50000 cents

# Trust-score signal constants (PRD §3.1 / §2.9).
BASE_TRUST = 50
VERIFY_BONUS = 20
UPHELD_PENALTY = 15
COMPLETION_BONUS = 6
COMPLETION_CAP = 5
TRUST_FLOOR = 0
TRUST_CEIL = 100
