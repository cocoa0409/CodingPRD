"""Domain thresholds and shared dates — numeric constants from PRD rules."""

# Logical clock startup default (PRD §2.4).
CLOCK_START = "2026-08-01T00:00:00Z"

# Day-count divisors per fund convention (PRD §3.5).
DAY_COUNT = {"ACT_365": 365, "ACT_360": 360}

# Expense-cap ratio annualization uses 365 days regardless of convention (PRD §3.5).
ANNUALIZATION_DAYS = 365

# Breaks escalate once break_date is MORE than this many days before the clock (PRD §3.8).
BREAK_ESCALATION_DAYS = 5

# Filing deadlines measured from period_end (PRD §3.9).
FILING_DEADLINE_DAYS = {"N_PORT": 60, "ANNUAL_REPORT": 60, "SEMI_ANNUAL_REPORT": 60, "N_CEN": 75}

# Fee year divisor (PRD §3.9).
FEE_YEAR_DAYS = 365

# Common business dates used across setups.
D_OPEN = "2026-08-03"        # position opened / subscription date
D_NAV = "2026-08-04"         # first accounting date
D_NAV_NEXT = "2026-08-05"    # second accounting date
D_PAYABLE = "2026-08-10"     # distribution payable date
T_NAV = "2026-08-04T00:00:00Z"
T_NAV_NEXT = "2026-08-05T00:00:00Z"
T_PAYABLE = "2026-08-10T00:00:00Z"

# Base-kit arithmetic (qty 1000 @ 100.00, 10000 shares, ACT_365, 10 bps):
# GAV 100000.00, daily admin accrual 0.27, TNA 99999.73, NAV/share 10.0000.
TEST_DEFAULTS = {
    "SHARES": 10000,
    "QUANTITY": 1000,
    "PRICE": 100.00,
    "ADMIN_FEE_BPS": 10,
    "BASE_GAV": 100000.00,
    "BASE_ACCRUAL": 0.27,
    "BASE_TNA": 99999.73,
    "BASE_NAV_PER_SHARE": 10.0000,
}
