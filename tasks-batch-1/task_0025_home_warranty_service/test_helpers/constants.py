"""Domain thresholds — numeric constants stated in the PRD."""

# PRD §3.8 — Renewal-premium calculation constants.
EARLY_RENEWAL_DAYS_THRESHOLD = 14   # D >= 15 (i.e., > 14) gets the 10% discount.
EARLY_RENEWAL_DISCOUNT_PCT = 0.10
ITEM_SURCHARGE_PCT_PER_ITEM = 0.02

# PRD §3.2 — Coverage window.
COVERAGE_DAYS = 365

# PRD §3.8 — Renewal reminder threshold (auto-transition ACTIVE → EXPIRING_SOON).
RENEWAL_REMINDER_LEAD_DAYS = 30

# PRD §3.5 — Technician dispatch buffer (seconds; strict less-than rejects).
TECHNICIAN_BUFFER_SECONDS = 3600

# PRD §2.3 — Pagination defaults.
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
