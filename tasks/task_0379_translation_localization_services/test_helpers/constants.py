"""Domain thresholds — numeric constants from the PRD pricing, payout, and QA rules.

These mirror the literal values stated in PRD §2.7, §3.3, §3.8, §3.9, and §3.10.
"""

# Band pay factors (PRD §3.3 / §3.9): weight applied to each translation-memory band.
PAY_FACTOR = {
    "NO_MATCH": 1.00,
    "FUZZY_75_99": 0.65,
    "REPS_100": 0.35,
    "CONTEXT_101": 0.15,
}

# Volume-discount tier boundaries on the weighted word total (PRD §3.3 step four).
VOLUME_TIER_HIGH_WORDS = 20000      # >= 20000 -> 10% discount
VOLUME_TIER_HIGH_PCT = 0.10
VOLUME_TIER_LOW_WORDS = 5000        # >= 5000 (and < 20000) -> 5% discount
VOLUME_TIER_LOW_PCT = 0.05

# Rush multiplier per rush tier (PRD §3.3 step five / §3.8).
RUSH_MULT = {
    "STANDARD": 1.00,
    "EXPRESS": 1.30,
    "SAME_DAY": 1.75,
}

# Certification add-on constants (PRD §3.3 step six / §3.7 / §3.8).
WORDS_PER_PAGE = 250
CERT_PER_PAGE_CENTS = 500
NOTARY_FLAT_CENTS = 3500

# Revision surcharge (PRD §3.8 fourth).
REVISION_SURCHARGE_PCT = 0.08
FREE_REVISION_ROUNDS = 1

# Linguist payout quality adjustment (PRD §3.9).
QA_BONUS_THRESHOLD = 95      # score >= 95 -> +5% bonus
QA_BONUS_PCT = 0.05
QA_REWORK_FLOOR = 80         # score < 80 -> -10% penalty
QA_PENALTY_PCT = 0.10

# QA scoring (PRD §3.10).
CRITICAL_W = 10
MAJOR_W = 5
MINOR_W = 1
QA_PASS_THRESHOLD = 90.0     # outcome PASS iff score >= 90.0

# Linguist registration default (PRD §3.1).
DEFAULT_DAILY_THROUGHPUT_WORDS = 2500

# Convenience defaults used across fixtures (rate card the design indices use).
TEST_DEFAULTS = {
    "BASE_RATE_CENTS_PER_WORD": 15,
    "LINGUIST_RATE_CENTS_PER_WORD": 9,
    "SOURCE_LOCALE": "en-US",
    "TARGET_LOCALE": "de-DE",
}
