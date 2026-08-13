"""Domain thresholds — numeric constants stated in the PRD prose."""

THRESHOLDS = {
    # APA tiered default (PRD 3.3): fee strictly below 2,000,000 -> 0.30, else 0.25.
    "APA_TIER_THRESHOLD_CENTS": 2000000,
    "APA_PCT_BELOW_THRESHOLD": 0.30,
    "APA_PCT_AT_OR_ABOVE_THRESHOLD": 0.25,
    # Funding schedule (PRD 3.4): signing charter part is half the fee, round half-up.
    "SIGNING_SHARE_PCT": 0.50,
    # Cancellation penalty tiers (PRD 3.9), in whole days before start.
    "TIER_FULL_NOTICE_DAYS": 90,
    "TIER_HIGH_NOTICE_DAYS": 60,
    "TIER_LOW_NOTICE_DAYS": 30,
    "PENALTY_COMMISSION_PCT": 0.20,
    # Commission tiers on the charter fee (PRD 3.8).
    "COMMISSION_TIER1_MAX_CENTS": 999999,
    "COMMISSION_TIER2_MAX_CENTS": 4999999,
    "COMMISSION_TIER1_RATE": 0.15,
    "COMMISSION_TIER2_RATE": 0.18,
    "COMMISSION_TIER3_RATE": 0.20,
    # Negotiation cap (PRD 3.3).
    "MAX_NEGOTIATION_ROUNDS": 4,
    # Offer validity in days (PRD 3.3).
    "OFFER_VALID_DAYS": 7,
    # Turnaround buffer in days (PRD 2.7).
    "TURNAROUND_BUFFER_DAYS": 1,
    # Quote formula (PRD 3.3).
    "DAYS_PER_WEEK": 7,
    "EXTRA_DAY_DIVISOR": 6,
    # CREWED gratuity minimum share of the quoted fee (PRD 3.3).
    "CREWED_GRATUITY_MIN_PCT": 0.10,
}

TEST_DEFAULTS = {
    # Basis-point split pinned explicitly on offers in fixtures so the
    # retail/central share arithmetic has a fully specified input.
    "RETAIL_PCT_BPS": 5000,
    # Logical clock startup default (PRD 2.5).
    "CLOCK_DEFAULT_ISO": "2026-08-01T00:00:00Z",
    # Standard yacht presets used across scenarios.
    "YACHT_A_WEEKLY_RATE": 700000,
    "YACHT_A_DEPOSIT": 500000,
    "YACHT_A_CAPACITY": 8,
    "YACHT_A_MIN_DAYS": 3,
}
