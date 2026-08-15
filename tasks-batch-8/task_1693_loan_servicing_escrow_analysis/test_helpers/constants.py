"""Domain thresholds and calendar constants from the PRD."""

# PRD §2.5: the logical clock before any set call.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# PRD §3.3 / §3.7: RESPA cushion = one-sixth of annual disbursements.
CUSHION_DIVISOR = 6

# PRD §3.7: shortage/deficiency repayment spread period.
SPREAD_MONTHS = 12

# PRD §3.7: surplus at or above this amount is refunded at finalize.
SURPLUS_REFUND_THRESHOLD_CENTS = 5000

# PRD §3.4: advance cap ($10,000.00) on total outstanding advances per account.
ADVANCE_CAP_CENTS = 1_000_000

# PRD §3.7: projection window length in days (closed interval).
WINDOW_DAYS = 364

# PRD §3.5: force-placement term and refund timeliness window.
FP_TERM_DAYS = 365
REFUND_WINDOW_DAYS = 15

# PRD §3.5: notice windows (days after notice dates).
FIRST_NOTICE_TO_REMINDER_DAYS = 30
FIRST_NOTICE_TO_CHARGE_DAYS = 45
REMINDER_TO_CHARGE_DAYS = 15

# PRD §3.6: redemption-risk escalation after delinquency.
REDEMPTION_RISK_DAYS = 730

# PRD §3.9: business-day deadlines for error cases.
ACK_BUSINESS_DAYS = 5
RESOLUTION_BUSINESS_DAYS = 30
EXTENDED_RESOLUTION_BUSINESS_DAYS = 45

# PRD §3.9: fixed federal holiday calendar used by business-day arithmetic.
FEDERAL_HOLIDAYS = [
    "2026-09-07", "2026-10-12", "2026-11-11", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-05-31", "2027-07-05",
    "2027-09-06", "2027-10-11", "2027-11-11", "2027-11-25", "2027-12-24",
    "2027-12-31",
]

# Standard loan input defaults used by factories.
TEST_DEFAULTS = {
    "PRINCIPAL_BALANCE_CENTS": 30_000_000,
    "MONTHLY_PI_CENTS": 180_000,
    "CLOSING_DATE": "2026-08-01",
}
