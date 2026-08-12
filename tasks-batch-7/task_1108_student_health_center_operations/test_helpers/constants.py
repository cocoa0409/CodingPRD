"""Domain thresholds and constants named in PRD §2.4, §3.4, §3.7, §3.8, §3.9."""

# PRD §2.4: startup default logical clock.
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# PRD §3.4: same-day triage daily quota per provider.
TRIAGE_DAILY_QUOTA = 4

# PRD §3.5: standard visit subsidy debited to the open pool on a fee-covered close.
VISIT_SUBSIDY_CENTS = 12000

# PRD §3.7: rolling-window outbreak threshold and emergency pool debit.
OUTBREAK_THRESHOLD = 3
OUTBREAK_WINDOW_HOURS = 168
OUTBREAK_EMERGENCY_DEBIT_CENTS = 25000

# PRD §3.7: case report window after confirmation (boundary inclusive).
REPORT_WINDOW_HOURS = 24

# PRD §3.8: travel-vaccine subsidy share and invoice due-date offset.
SUBSIDY_PCT = 0.5
INVOICE_DUE_DAYS = 30

# PRD §3.9: business-hours window (half-open) and on-call rest buffer.
BUSINESS_HOURS_START = "08:00"
BUSINESS_HOURS_END = "17:00"
ONCALL_REST_HOURS = 12
