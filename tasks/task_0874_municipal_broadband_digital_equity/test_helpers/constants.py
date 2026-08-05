"""Domain thresholds — numeric constants from the PRD calculations (§2, §3)."""

# Minutes in the standard monthly billing period (SLA-credit denominator, §3.6).
MINUTES_IN_BILLING_PERIOD = 43200

# Buffer around an OPEN outage within which a new outage collides (§3.6).
OUTAGE_MERGE_BUFFER_MINUTES = 60

# Federal share applied per subsidized subscriber for grant reimbursement (§3.7).
FEDERAL_SHARE_PCT = 33.34

# Certification validity period in days for an active enrollment (§3.4).
CERT_PERIOD_DAYS = 365

# Annual Federal-Poverty-Level base amounts in cents, keyed by household size (§3.4).
FPL_BASE_CENTS = {
    1: 1506000,
    2: 2034000,
    3: 2562000,
    4: 3090000,
    5: 3618000,
}

# Convenience default price used across pricing scenarios.
STANDARD_PLAN_PRICE_CENTS = 6000
