"""Domain thresholds and pinned fixture values (PRD §2.5, §2.6, §3)."""

THRESHOLDS = {
    # Fixed credit pass threshold (PRD §3.4).
    "CREDIT_PASS_BPS": 6000,
    # Minimum marketing completeness at submit (PRD §3.4).
    "MIN_MARKETING_DAYS": 30,
    # METHOD_B common-area add-on in basis points (PRD §3.3).
    "METHOD_B_COMMON_ADDON_BPS": 250,
    # Partial-floor expense gross-up in basis points (PRD §3.8).
    "PARTIAL_FLOOR_GROSSUP_BPS": 1500,
    # Settlement day-count year (PRD §3.8).
    "DAYS_PER_YEAR": 365,
    # Extra business days after the deadline before deemed approval (PRD §3.6).
    "DEEMED_REMINDER_EXTRA_BDAYS": 2,
    # Credit rating scale bounds (PRD §2.6).
    "CREDIT_RATING_MIN_BPS": 0,
    "CREDIT_RATING_MAX_BPS": 10000,
    # Consent window bounds (PRD §3.1).
    "CONSENT_WINDOW_MIN_DAYS": 1,
    "CONSENT_WINDOW_MAX_DAYS": 60,
}

# Standard fixture economics used across the suite:
# building 200,000 RSF with 1,200 bps loss factor; lease 5,200 c/RSF/yr base,
# 5-business-day consent window, deemed approval enabled, tier1 5,000 bps up to
# 10,000,000 c/yr then tier2 7,500 bps; measurement METHOD_A usable 8,000 SF
# (certifies to 8,960 RSF, pro-rata 448 bps); transfer rent 6,400 c/RSF/yr.
TEST_DEFAULTS = {
    "BUILDING_NAME": "Tower One",
    "BUILDING_TOTAL_RENTABLE_SF": 200000,
    "BUILDING_LOSS_FACTOR_BPS": 1200,
    "BASE_RENT_PER_RSF_ANNUAL_CENTS": 5200,
    "LEASED_RSF": 10000,
    "LEASED_RSF_FULL_FLOOR": 8000,
    "CONSENT_WINDOW_BUSINESS_DAYS": 5,
    "DEEMED_APPROVAL_ENABLED": True,
    "TIER1_PCT_BPS": 5000,
    "TIER1_THRESHOLD_ANNUAL_CENTS": 10000000,
    "TIER2_PCT_BPS": 7500,
    "MEASUREMENT_STANDARD": "METHOD_A",
    "USABLE_SF": 8000,
    "PROPOSED_RENT_PER_RSF_ANNUAL_CENTS": 6400,
    "TERM_START": "2026-09-01T00:00:00.000Z",
    "TERM_END": "2027-08-31T00:00:00.000Z",
    "MARKETING_PERIOD_DAYS": 45,
    "PARTY_CREDIT_LANDLORD": 9000,
    "PARTY_CREDIT_TENANT": 8000,
    "PARTY_CREDIT_COUNTERPARTY": 7000,
    "ATTESTED_CREDIT_RATING_BPS": 7000,
    # October 2026 accrual window used by settlement tests (31 whole days).
    "PERIOD_START_OCT": "2026-10-01T00:00:00.000Z",
    "PERIOD_END_NOV": "2026-11-01T00:00:00.000Z",
    "PERIOD_END_DEC": "2026-12-01T00:00:00.000Z",
    "SUBRENT_COLLECTED_CENTS": 6000000,
}

# Logical-clock anchors (PRD §2.5: startup clock is 2026-08-01T00:00:00.000Z).
CLOCK = {
    # A Monday; with a 5-business-day window the deadline is Mon 2026-08-17 17:00Z.
    "MONDAY_SUBMIT": "2026-08-10T09:00:00.000Z",
    "MONDAY_DEADLINE": "2026-08-17T17:00:00.000Z",
    # A Friday; the 5-business-day window skips the weekend to Fri 2026-08-21 17:00Z.
    "FRIDAY_SUBMIT": "2026-08-14T09:00:00.000Z",
    "FRIDAY_DEADLINE": "2026-08-21T17:00:00.000Z",
    # Deemed-approval instant for the Monday anchor: deadline + 2 business days.
    "DEEMED_INSTANT": "2026-08-19T17:00:00.000Z",
    "DEEMED_INSTANT_MINUS_1MIN": "2026-08-19T16:59:00.000Z",
    # One minute past the Monday deadline (reminder becomes eligible).
    "AFTER_DEADLINE": "2026-08-17T18:00:00.000Z",
    "JUST_AFTER_DEADLINE": "2026-08-17T17:00:01.000Z",
    # General setup instant (Monday before the submit anchors).
    "SETUP": "2026-08-03T09:00:00.000Z",
}
