"""Domain thresholds and numeric constants from the PRD's calculation rules."""

# Catering (PRD §3.1, §3.6)
DEFAULT_CATERING_CUTOFF_HOURS = 72
SERVICE_FEE_RATE_NUM = 18  # 18% service fee on the subtotal
SERVICE_FEE_RATE_DEN = 100
CATERING_LATE_CANCEL_FEE_NUM = 1  # half of total_cents
CATERING_LATE_CANCEL_FEE_DEN = 2

# License fees (PRD §3.3)
ESCALATOR_BP_DEN = 10000
TERM_SEASONS_MIN = 1
TERM_SEASONS_MAX = 10
ESCALATOR_BP_MAX = 2000

# Late fees (PRD §3.4)
LATE_FEE_PERIOD_DAYS = 30
LATE_FEE_PERIOD_RATE_NUM = 15   # 1.5% per period
LATE_FEE_PERIOD_RATE_DEN = 1000
LATE_FEE_MIN_CENTS = 2500
LATE_FEE_CAP_RATE_NUM = 15      # 15% of subtotal
LATE_FEE_CAP_RATE_DEN = 100

# Rentals (PRD §3.8)
TIER_MULTIPLIERS = {"FOUNDERS": (160, 100), "PLATINUM": (130, 100),
                    "GOLD": (100, 100), "SILVER": (80, 100)}
PER_GUEST_OVERAGE_CENTS = 1500
PLAYOFF_MULT_NUM = 125
PLAYOFF_MULT_DEN = 100
DEPOSIT_RATE_NUM = 30
DEPOSIT_RATE_DEN = 100
HOLD_HOURS = 48
RENTAL_INVOICE_DUE_DAYS_BEFORE_EVENT = 7
RENTAL_CANCEL_FEE_TIERS = [  # (min_whole_days_to_event, pct of quoted)
    (14, 10),
    (7, 30),
    (3, 50),
    (0, 100),
]
RENTAL_CANCEL_INVOICE_DUE_DAYS = 14

# Transfers (PRD §3.9)
TRANSFER_FEE_FLAT_MIN_CENTS = 50000
TRANSFER_FEE_SALE_TIERS = [  # (elapsed_fraction_lower_bound_inclusive, pct)
    (0.75, 3),
    (0.25, 6),
    (0.0, 10),
]
TRANSFER_FEE_SUBLEASE_PCT = 5
TRANSFER_FEE_INVOICE_DUE_DAYS = 14

# Invoices (PRD §3.4)
AUTO_INVOICE_DUE_DAYS = 30  # LICENSE_FEE / F_B_SHORTFALL / TERMINATION_FEE
ASSESSMENT_INVOICE_DUE_DAYS = 60

# Credentials (PRD §3.7)
CREDENTIAL_WINDOW_PRE_START_HOURS = 4

# Waitlist (PRD §3.10)
WAITLIST_WAITING_PERIOD_DAYS = 30
WAITLIST_WAITING_CAP_PERIODS = 10
WAITLIST_SPEND_UNIT_CENTS = 100000
WAITLIST_SPEND_CAP_POINTS = 50

# Common ISO instants used across fixtures
CLOCK_T0 = "2026-08-01T00:00:00Z"  # startup default
SEASON1 = {
    "label": "2026-27",
    "starts_on": "2026-09-01T00:00:00Z",
    "ends_on": "2027-02-15T00:00:00Z",
    "renewal_window_opens_on": "2026-12-01T00:00:00Z",
    "renewal_window_closes_on": "2027-01-15T00:00:00Z",
}
SEASON2 = {
    "label": "2027-28",
    "starts_on": "2027-09-01T00:00:00Z",
    "ends_on": "2028-02-15T00:00:00Z",
    "renewal_window_opens_on": "2027-12-01T00:00:00Z",
    "renewal_window_closes_on": "2028-01-15T00:00:00Z",
}
SEASON3 = {
    "label": "2028-29",
    "starts_on": "2028-09-01T00:00:00Z",
    "ends_on": "2029-02-15T00:00:00Z",
    "renewal_window_opens_on": "2028-12-01T00:00:00Z",
    "renewal_window_closes_on": "2029-01-15T00:00:00Z",
}
EVENT_E1 = {  # REGULAR opener, cutoff 2026-09-07T17:00Z at the 72h default
    "name": "Opener", "event_type": "REGULAR",
    "starts_at": "2026-09-10T17:00:00Z", "duration_hours": 4,
    "rental_base_price_cents": 500000,
}
EVENT_E1_CUTOFF = "2026-09-07T17:00:00Z"
EVENT_E2 = {  # RIVALRY
    "name": "Rivalry Week", "event_type": "RIVALRY",
    "starts_at": "2026-10-05T17:00:00Z", "duration_hours": 4,
    "rental_base_price_cents": 650000,
}
EVENT_E5 = {  # PLAYOFF
    "name": "Semifinal", "event_type": "PLAYOFF",
    "starts_at": "2027-01-10T20:00:00Z", "duration_hours": 5,
    "rental_base_price_cents": 1200000,
}
