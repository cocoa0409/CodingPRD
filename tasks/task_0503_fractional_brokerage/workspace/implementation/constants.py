"""Domain constants (SCAFFOLD §1.3, PRD §3)."""

INSTANT_CAP_CENTS = 10_000_000       # $100,000 cumulative provisional-credit ceiling
MARGIN_MULTIPLIER = 2
LONG_TERM_DAYS = 365
PDT_THRESHOLD = 4
PDT_MIN_EQUITY_CENTS = 2_500_000     # $25,000
WINDOW_BUSINESS_DAYS = 5
DIVIDEND_WINDOW_DAYS = 30            # calendar days
MARGIN_CURE_DAYS = 4                 # business days

VENUE_REBATE_BPS = {
    "VENUE_A": 30,
    "VENUE_B": 20,
    "VENUE_C": 10,
}
EQUITY_VENUES = ["VENUE_A", "VENUE_B", "VENUE_C"]
OPTION_VENUES = ["VENUE_A", "VENUE_B"]
