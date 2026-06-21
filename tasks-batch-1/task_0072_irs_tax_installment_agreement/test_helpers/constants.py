"""Domain thresholds — numeric constants from PRD calculations and rules."""

# Penalty / interest rates (§3.6)
STANDARD_FTP_RATE = 0.005       # standard failure-to-pay penalty, per month
DDIA_FTP_RATE = 0.0025          # DDIA-reduced penalty rate, per month
MONTHLY_INTEREST_RATE = 0.006   # fixed monthly interest rate

# Setup fee (§3.7)
DDIA_SETUP_FEE_CENTS = 3100
MANUAL_SETUP_FEE_CENTS = 14900

# CSED statute window (§3.1)
CSED_BASE_DAYS = 3653           # 10 years incl. 2 leap days

# Agreement window buffer (§3.4)
AGREEMENT_BUFFER_DAYS = 30

# Missed-debit default threshold (§3.5)
MISSED_DEBIT_DEFAULT_THRESHOLD = 2

# Short-term agreement maximum (§3.4)
SHORT_TERM_MAX_MONTHS = 6

# RCP future-income multipliers (§3.9)
MULT_SHORT = 12
MULT_MID = 24
MULT_LONG = 60

THRESHOLDS = {
    "STANDARD_FTP_RATE": STANDARD_FTP_RATE,
    "DDIA_FTP_RATE": DDIA_FTP_RATE,
    "MONTHLY_INTEREST_RATE": MONTHLY_INTEREST_RATE,
    "DDIA_SETUP_FEE_CENTS": DDIA_SETUP_FEE_CENTS,
    "MANUAL_SETUP_FEE_CENTS": MANUAL_SETUP_FEE_CENTS,
    "CSED_BASE_DAYS": CSED_BASE_DAYS,
    "AGREEMENT_BUFFER_DAYS": AGREEMENT_BUFFER_DAYS,
    "MISSED_DEBIT_DEFAULT_THRESHOLD": MISSED_DEBIT_DEFAULT_THRESHOLD,
    "SHORT_TERM_MAX_MONTHS": SHORT_TERM_MAX_MONTHS,
    "MULT_SHORT": MULT_SHORT,
    "MULT_MID": MULT_MID,
    "MULT_LONG": MULT_LONG,
}
