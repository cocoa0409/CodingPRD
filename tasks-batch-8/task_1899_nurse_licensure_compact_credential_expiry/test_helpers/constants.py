"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock startup default (PRD §2.5): before the clock is ever set it reads
# exactly this instant.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Compact state set and facility state (PRD §3.3).
COMPACT_STATES = ["AZ", "CO", "FL", "GA", "MD", "NC", "TN", "TX"]
FACILITY_STATE = "TX"

# Verification freshness window in days (PRD §3.2).
PSV_VALIDITY_DAYS = 180

# Proactive ACTIVE-license renewal window in days (PRD §3.2).
RENEWAL_WINDOW_DAYS = 60

# Scheduling horizon in days past the current date (PRD §3.6).
SCHEDULING_HORIZON_DAYS = 90

# Weekly labor budget cap in whole minutes (PRD §3.6) — 60 hours.
WEEKLY_HOUR_CAP_MINUTES = 3600

# Expiry report bucket thresholds in integer days (PRD §3.9).
CRITICAL_DAYS = 30
WARNING_DAYS = 60

# Readiness-score critical cap and partial credits (PRD §3.7).
CRITICAL_CAP = 0.49
WAIVER_CREDIT = 0.5
SUBMITTED_CREDIT = 0.25

# Packet item weights (PRD §3.7).
PACKET_ITEM_WEIGHTS = {
    "LICENSE_VERIFICATION": 40,
    "BLS": 20,
    "ACLS": 20,
    "COMPETENCY_ANNUAL": 15,
    "ATTESTATION": 5,
}

# Fiscal-year end used by FISCAL window mode (PRD §3.4).
FISCAL_MONTH_DAY = "06-30"

# Minimum active period per disciplinary severity before resolution (PRD §3.8).
MIN_ACTIVE_DAYS = {
    "REPRIMAND": 0,
    "PROBATION": 90,
    "SUSPENSION": 30,
    "REVOCATION": 365,
}

TEST_DEFAULTS = {
    "NURSE_PSOR": "AZ",
    "NURSE_EMPLOYMENT_TYPE": "STAFF",
    "NURSE_HIRE_DATE": "2026-07-01",
    "LICENSE_STATE": "AZ",
    "LICENSE_CLASS": "RN",
    "LICENSE_ISSUED_ON": "2026-06-15",
    "LICENSE_EXPIRES_ON": "2027-06-30",
    "CERT_ISSUING_BODY": "AHA",
    "BLS_EXPIRES_ON": "2027-03-31",
    "COMPLETED_ON": "2026-07-15",
}
