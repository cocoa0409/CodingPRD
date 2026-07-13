"""Domain thresholds and money constants stated in the PRD."""

# PRD §2.5 — the logical clock's startup default.
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

# PRD §3.2 — TLD list prices and the premium multiplier.
TLD_BASE_PRICE_CENTS = {"com": 1199, "net": 1499, "io": 3999, "xyz": 199}
PREMIUM_MULTIPLIER = 5
PREMIUM_MAX_LABEL_LENGTH = 3

# PRD §3.2 / §3.4 — privacy and redemption fees, term ceiling.
PRIVACY_FEE_CENTS_PER_YEAR = 999
REDEMPTION_FEE_CENTS = 8000
MAX_TERM_YEARS = 10

# PRD §3.8 — tax, service-fee tiers.
TAX_RATE = 0.0825
SERVICE_FEE_TIER1_MAX = 5000
SERVICE_FEE_TIER2_MAX = 20000
SERVICE_FEE_T0_CENTS = 0
SERVICE_FEE_T1_CENTS = 299
SERVICE_FEE_T2_CENTS = 999

# PRD §3.5 — add-on prices and the certificate buffer.
SSL_PRICE_CENTS = 5999
MAILBOX_PRICE_CENTS_PER_GB = 399
MB_PER_GB = 1024
SSL_RENEWAL_BUFFER_DAYS = 1

# PRD §3.6 — overage tiers and the billing-period length.
OVERAGE_TIER1_GB = 10
OVERAGE_TIER2_GB = 40
OVERAGE_TIER2_FACTOR = 0.75
OVERAGE_TIER3_FACTOR = 0.5
BILLING_PERIOD_DAYS = 30

# PRD §3.4 — the expiry/redemption ladder and the ICANN lock window.
EXPIRY_GRACE_DAYS = 30
REDEMPTION_DAYS = 30
PENDING_DELETE_DAYS = 5
TRANSFER_LOCK_DAYS = 60
DAYS_PER_YEAR = 365

# PRD §3.7 — the bounded EPP negotiation cycle.
MAX_TRANSFER_ATTEMPTS = 3

# PRD §3.9 — risk scoring.
SEVERITY_WEIGHT = {"LOW": 10, "HIGH": 30, "CRITICAL": 60}
DECAY_FACTOR = 0.5
DECAY_HALFLIFE_DAYS = 90
AUTO_SUSPEND_THRESHOLD = 70
RISK_SCORE_CAP = 100

# PRD §2.3 — pagination.
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# PRD §3.2 — the Anonymous WHOIS projection.
WHOIS_REDACTED_NAME = "REDACTED FOR PRIVACY"
WHOIS_REDACTED_EMAIL = "privacy@proxy.example"

# Convenience defaults used by the test factories.
TEST_DEFAULTS = {
    "CARD_TOKEN": "tok_visa_4242",
    "REGISTRANT_NAME": "Ada L",
    "REGISTRANT_EMAIL": "ada@corp.example",
    "REPORTER_EMAIL": "watch@ngo.example",
    "COMPANY_NAME": "Corp Example",
    "PLAN_STORAGE_QUOTA_MB": 5120,
    "PLAN_BANDWIDTH_QUOTA_MB": 10240,
    "PLAN_MONTHLY_PRICE_CENTS": 4999,
    "PLAN_OVERAGE_RATE_CENTS_PER_GB": 200,
}
