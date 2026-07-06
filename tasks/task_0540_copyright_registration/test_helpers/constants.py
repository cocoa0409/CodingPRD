"""Domain constants that the PRD states numerically.

Only values the PRD prose fixes exactly are listed here. Statutory-window
day/year spans that the PRD names only symbolically (correspondence deadline,
DMCA restoration window, certificate renewal term, deposit copy minimums) are
deliberately NOT encoded — tests that would depend on those unstated numbers
are not generated.
"""

# Filing-fee arithmetic (PRD §3.2, all stated in cents).
SINGLE_BASE = 4500          # single-work base ($45.00)
STANDARD_BASE = 6500        # standard base ($65.00)
ADDL_CLAIMANT = 1500        # additional-claimant surcharge ($15.00)
EXPEDITE_SURCHARGE = 80000  # expedite surcharge ($800.00)

# Basis points (PRD §2.7).
BPS_DENOMINATOR = 10000

# Statutory termination window (PRD §3.7, calendar years, inclusive bounds).
TERMINATION_WINDOW_START_YEARS = 35
TERMINATION_WINDOW_SPAN_YEARS = 5

# Logical-clock startup default (PRD §2.5).
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"
