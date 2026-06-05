"""Domain thresholds — numeric constants from PRD calculations and policy rules."""

# Cross-cutting policy constants (PRD §3.5, §3.7).
MIN_WORK_SEARCH_CONTACTS = 3       # weeks needing work search require >= 3 contacts
MAX_REMANDS = 2                    # an appeal may be remanded at most twice
APPEAL_WINDOW_DAYS = 30            # appeal deadline = determination date + 30 days

# Monetary qualification (PRD §3.2).
QUALIFYING_MIN_TOTAL_CENTS = 260000     # $2,600 minimum base-period wages
HIGH_QUARTER_MIN_CENTS = 130000         # $1,300 minimum high-quarter wages
TOTAL_OVER_HIGHQ_MULTIPLE = 1.5         # base_total >= 1.5 * high_quarter

# Weekly benefit amount (PRD §3.3).
WBA_DIVISOR = 26
WBA_FLOOR_CENTS = 4000      # $40 minimum weekly benefit
WBA_CEILING_CENTS = 60000   # $600 maximum weekly benefit

# Maximum benefit amount (PRD §3.4).
MAX_REGULAR_WEEKS = 26
MBA_WAGE_FRACTION = 0.5     # MBA wage cap = 50% of base-period total wages

# Earnings disregard (PRD §3.5.1).
EARNINGS_DISREGARD_PCT = 0.25         # disregard 25% of WBA
EARNINGS_DISREGARD_FLOOR_CENTS = 5000  # but never less than $50

# Fraud penalty (PRD §3.8).
FRAUD_PENALTY_RATE = 0.15   # 15% penalty on fraudulent overpayments

THRESHOLDS = {
    "MIN_WORK_SEARCH_CONTACTS": MIN_WORK_SEARCH_CONTACTS,
    "MAX_REMANDS": MAX_REMANDS,
    "APPEAL_WINDOW_DAYS": APPEAL_WINDOW_DAYS,
    "QUALIFYING_MIN_TOTAL_CENTS": QUALIFYING_MIN_TOTAL_CENTS,
    "HIGH_QUARTER_MIN_CENTS": HIGH_QUARTER_MIN_CENTS,
    "WBA_DIVISOR": WBA_DIVISOR,
    "WBA_FLOOR_CENTS": WBA_FLOOR_CENTS,
    "WBA_CEILING_CENTS": WBA_CEILING_CENTS,
    "MAX_REGULAR_WEEKS": MAX_REGULAR_WEEKS,
    "MBA_WAGE_FRACTION": MBA_WAGE_FRACTION,
    "EARNINGS_DISREGARD_PCT": EARNINGS_DISREGARD_PCT,
    "EARNINGS_DISREGARD_FLOOR_CENTS": EARNINGS_DISREGARD_FLOOR_CENTS,
    "FRAUD_PENALTY_RATE": FRAUD_PENALTY_RATE,
}

# A non-existent but well-formed UUID for not-found tests (matches corner-design literals).
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
