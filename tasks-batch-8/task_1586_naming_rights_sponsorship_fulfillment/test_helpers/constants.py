"""Domain thresholds and numeric constants from the PRD's calculation rules."""

# Venue epoch: every new venue starts at this season (PRD section on the
# season epoch and the advance-season checkpoint).
INITIAL_SEASON = 2026

# Installment split percentages applied to a contract's scheduled total at
# countersign: SIGNING 40% / MID_SEASON 30% / POST_SEASON remainder.
SIGNING_PCT = 0.40
MID_SEASON_PCT = 0.30

# Make-good credit tier thresholds on the fulfillment fraction
# (approved_units / contracted_units, compared as an exact ratio):
#   fraction >= 0.90  -> multiplier 1.00
#   0.70 <= fraction < 0.90 -> multiplier 1.25
#   fraction < 0.70 -> multiplier 1.50
MAKE_GOOD_TIER1_PCT = 0.90
MAKE_GOOD_TIER1_MULT = 1.00
MAKE_GOOD_TIER2_PCT = 0.70
MAKE_GOOD_TIER2_MULT = 1.25
MAKE_GOOD_TIER3_MULT = 1.50

# Suite-night turnaround buffer: a booking blocks its checkout day plus one
# additional day.
TURNAROUND_BUFFER_DAYS = 1

TEST_DEFAULTS = {
    "VENUE_DISPLAY_NAME": "Vector Arena",
    "VENUE_CITY": "Austin",
    "SPONSOR_LEGAL_NAME": "FizzCo Beverages LLC",
    "SPONSOR_DISPLAY_NAME": "FizzCo",
    "SPONSOR_CATEGORY": "BEVERAGE",
    "ASSET_NAME": "Bowl LED Ribbon",
    "ASSET_CLASS": "SIGNAGE",
    "RATE_CARD_UNIT_CENTS": 50_000,
    "AVG_IMPRESSIONS_PER_UNIT": 120_000,
    "CPM_CENTS": 2_500,
    "BASE_FEE_CENTS": 10_000_000,
    "CONTRACTED_UNITS": 10,
    "EVIDENCE_URI": "s3://pop/evidence.pdf",
    "PAYMENT_METHOD": "ACH",
}
