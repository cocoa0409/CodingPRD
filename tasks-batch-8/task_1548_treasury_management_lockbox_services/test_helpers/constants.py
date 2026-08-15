"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Earnings credit day-count convention (PRD §2.7 / §3.7)
DAY_COUNT_BASIS = 360
BP_DENOMINATOR = 10000

# SLA credit (PRD §3.8): on breach, ten percent of gross service charges
SLA_CREDIT_RATE_NUM = 10
SLA_CREDIT_RATE_DEN = 100

# Image retention (PRD §3.5): seven years from the item's capture timestamp
RETENTION_YEARS = 7

# Bank defaults at creation (PRD §3.1 / §2.5)
DEFAULT_BUSINESS_DATE = "2026-08-01"
DEFAULT_CYCLE_INDEX = 0
DEFAULT_SLA_BREACH_THRESHOLD_BP = 200

# Logical clock default at server startup (PRD §2.5)
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "BANK_LEGAL_NAME": "First Treasury Bank",
    "BANK_ROUTING_NUMBER": "021000089",
    "BANK_ECR_BP": 100,
    "CUSTOMER_LEGAL_NAME": "Acme Corp",
    "CUSTOMER_TAX_ID": "12-3456789",
    "CUSTOMER_DDA": "DDA-1001",
    "AGREEMENT_NUMBER": "AGR-001",
    "SITE_CODE": "LBX-CHI-01",
    "SITE_POSTAL_BOX": "PO Box 100, Chicago IL",
    "SITE_CUTOFF": "14:00",
    "SITE_TIMEZONE": "America/Chicago",
    "SCHEDULE_PATTERN": "0710",
    # 9-digit ABA per PRD §3.4, matching the "0710" schedule prefix.
    "PAYER_ROUTING": "071000288",
    # 2026-08-01T13:00:00Z == 08:00 in America/Chicago, strictly before a
    # 14:00 local cutoff, so a batch books to the current business date.
    "RECEIVED_BEFORE_CUTOFF": "2026-08-01T13:00:00Z",
}
