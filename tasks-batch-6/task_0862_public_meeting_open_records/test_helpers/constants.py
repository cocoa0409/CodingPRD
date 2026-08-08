"""Domain thresholds — numeric constants from PRD calculations (§3.7-§3.9)."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID  # noqa: F401

# Copy-fee schedule (PRD §3.7)
FREE_PAGE_ALLOWANCE = 50
COPY_TIER1_LIMIT = 500          # running total up to which tier-1 applies
COPY_TIER1_RATE_CENTS = 15
COPY_TIER2_RATE_CENTS = 10

# Labor-fee schedule (PRD §3.8)
LABOR_INCREMENT_MINUTES = 15
LABOR_FREE_MINUTES = 30
LABOR_RATE_CENTS_PER_HOUR = 2500

# Notice lead-time minimums, in hours (PRD §3.3)
NOTICE_LEAD_HOURS_REGULAR = 72
NOTICE_LEAD_HOURS_SPECIAL = 24
NOTICE_LEAD_HOURS_EMERGENCY = 1

# Response deadline (PRD §3.7)
RESPONSE_DEADLINE_BUSINESS_DAYS = 10

# Comment cap (PRD §3.4)
ITEM_COMMENT_CAP_SECONDS = 1800

# Venue setup buffer (PRD §3.2)
SETUP_BUFFER_MINUTES = 30

# Retention / appeal windows (PRD §3.9)
RETENTION_YEARS_PERMANENT = 9999
RETENTION_YEARS_FISCAL = 7
RETENTION_YEARS_ADMIN = 3
RETENTION_YEARS_TRANSITORY = 1
APPEAL_WINDOW_DAYS = 30
DAYS_PER_YEAR = 365

# Server startup default logical clock (PRD §2.6)
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"
