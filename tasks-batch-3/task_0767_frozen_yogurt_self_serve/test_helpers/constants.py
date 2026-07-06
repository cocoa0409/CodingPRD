"""Domain thresholds — numeric constants stated verbatim in the PRD.

Only constants whose values appear in PRD prose are listed here. The sanitation
cleaning interval and the maintenance spacing buffer are referenced in the PRD
only as named symbols without numeric values, so no literal for them is defined
(tests must not assume a specific value for either).
"""

# PRD §3.5: "minimum ticket charge of 100 cents".
MIN_TICKET_CHARGE_CENTS = 100

# PRD §3.5/§3.8: "one point per whole hundred cents" / "divided by 100".
POINTS_DIVISOR = 100

# PRD §3.8: "Whenever punch_count reaches or exceeds the punch threshold of 10".
PUNCH_THRESHOLD = 10

# PRD §3.8: "a fixed cash-off value_cents of 500".
VOUCHER_VALUE_CENTS = 500

# PRD §3.8: "an expires_at set to the issuing clock plus a time-to-live of 720 hours".
VOUCHER_TTL_HOURS = 720

# PRD §3.7: "the fixed per-unit topping cost of 12 cents".
TOPPING_UNIT_COST_CENTS = 12

# PRD §3.9: "required_deposit_cents is 25 percent of invoice_total_cents".
CATERING_DEPOSIT_PCT = 0.25

# PRD §2.4: startup logical-clock default.
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"

# A clock far enough in the future that a machine created at CLOCK_DEFAULT is
# overdue for cleaning under any plausible (hourly-scale) cleaning interval.
CLOCK_FAR_FUTURE = "2099-01-01T00:00:00Z"
