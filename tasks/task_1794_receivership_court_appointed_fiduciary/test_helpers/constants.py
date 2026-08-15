"""Domain thresholds and shared default payloads from PRD §2-§3."""

# --- Logical clock (PRD §2.5) ---
# Startup default before any set call.
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

# --- Claim bucketing (PRD §3.4) ---
WAGE_PRIORITY_CAP_CENTS = 1515000  # statutory wage-priority cap of $15,150.00

# --- Priority-class rank order (PRD §3.7) ---
PRIORITY_CLASS_RANK = {"SECURED": 1, "PRIORITY": 2, "GENERAL": 3, "INVESTOR": 4}

# --- Shared test defaults ---
TEST_DEFAULTS = {
    "COURT_JURISDICTION": "S.D.N.Y.",
    "DEBTOR_NAME": "Acme Widgets LLC",
    "APPOINTED_RECEIVER_NAME": "R. Receiver",
    "APPOINTMENT_EFFECTIVE_AT": "2026-08-01T00:00:00Z",
    "AUTHORITY_LIMIT_CENTS": 500000,
    "BUSINESS_OPERATION_AUTHORIZED": True,
    "BAR_DATE": "2026-09-01T00:00:00Z",
    "REPORTING_INTERVAL_DAYS": 30,
    "OPERATING_RESERVE_CENTS": 100000,
    "HOURLY_RATE_CENTS": 20000,
    "FEE_CAP_CENTS": 1000000,
}
