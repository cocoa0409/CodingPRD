# Domain constants from the scaffold's constants_glossary.
INCEPTION_UNIT_PRICE_MILLICENTS = 100000   # $1.000 per unit at pool inception
MIN_ENDOWMENT_CORPUS_CENTS = 5000000       # $50,000.00 minimum to activate
LAPSE_QUARTERS = 4                         # payout unspent sweeps at age >= 4 quarters
QUARTER_DAYS = 90                          # every quarter is exactly 90 days
QUARTERS_PER_FISCAL_YEAR = 4
UNIT_SCALE = 1000000                       # micro-units per unit
PRICE_SCALE = 1000                         # millicents per cent
VALUE_DIVISOR = 1000000000                 # 1e9: micro-units * millicents / 1e9 = cents

ALL_ROLES = [
    "EndowmentAdmin",
    "InvestmentOfficer",
    "DevelopmentOfficer",
    "BoardMember",
    "ProgramManager",
]

DONOR_TYPES = ["INDIVIDUAL", "FOUNDATION", "CORPORATION", "ESTATE"]
ENDOWMENT_CLASSES = ["TRUE_ENDOWMENT", "QUASI_ENDOWMENT", "TERM_ENDOWMENT"]
PURPOSE_RESTRICTIONS = ["UNRESTRICTED", "SCHOLARSHIP", "PROFESSORSHIP", "RESEARCH", "CAPITAL_PROJECTS"]
GIFT_TYPES = ["CORPUS", "EXPENDABLE"]
PROGRAM_PURPOSES = ["SCHOLARSHIP", "PROFESSORSHIP", "RESEARCH", "CAPITAL_PROJECTS"]
ASSET_CLASSES = [
    "US_EQUITY", "DEVELOPED_INTL_EQUITY", "EMERGING_MARKETS",
    "FIXED_INCOME", "REAL_ASSETS", "PRIVATE_EQUITY", "CASH",
]
REPORT_TYPES = ["DONOR_FUND", "BOARD_INVESTMENT", "SPENDING_COMPLIANCE"]
