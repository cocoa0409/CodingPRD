"""Domain thresholds — numeric constants stated in the PRD (§2.5, §3)."""

# Logical clock startup value (PRD §2.5).
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# Holding-time allowances in hours per parameter (PRD §3.3).
HOLDING_TIME_HOURS = {
    "BOD5": 48,
    "TSS": 168,
    "PH": 2,
    "AMMONIA_N": 672,
    "COPPER": 4320,
    "FECAL_COLIFORM": 8,
}

# Statutory notification windows in hours (PRD §3.4).
ORAL_WINDOW_HOURS = 24
WRITTEN_WINDOW_HOURS = 120

# Corrective-action deadlines in days, keyed by severity (PRD §3.6).
CA_DEADLINE_DAYS = {"CRITICAL": 7, "MAJOR": 30, "MINOR": 90}

# Inspection minimum spacing in days (PRD §3.6).
MIN_INSPECTION_GAP_DAYS = 7

# DMR due-date offset in days (PRD §3.5).
DMR_DUE_DAYS_AFTER_PERIOD = 15

# DMR certification completeness floor (PRD §3.5).
DMR_CERTIFY_MIN_RATIO = 0.5

# Renewal submission window: 180 days before expiration (PRD §3.7).
RENEWAL_WINDOW_DAYS = 180

# Concentration/flow to mass loading conversion (PRD §2.6).
KG_PER_MG_L_MGD = 3.785

# Penalty accrual (PRD §3.8).
DAYS_PER_MONTH = 30
MITIGATION_MAX_RATIO = 0.25

# Default collection window for sampling events (PRD §3.2).
DEFAULT_COLLECTION_WINDOW_HOURS = 24
