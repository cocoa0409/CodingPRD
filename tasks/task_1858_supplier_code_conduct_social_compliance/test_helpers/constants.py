"""Domain thresholds and numeric constants from the PRD (§2.5, §2.8, §3)."""

# --- The program logical clock (PRD §2.5) ---
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# --- Facility risk model (PRD §3.2) ---
COUNTRY_RISK = {"BD": 60, "IN": 55, "VN": 50, "CN": 40, "TR": 35, "US": 10}
SECTOR_MULT = {"APPAREL": 1.2, "ELECTRONICS": 1.1, "FOOD": 1.0, "HARDLINES": 0.9}
WORKER_FACTOR_T1_MIN = 1000   # worker_count >= 1000 -> +15
WORKER_FACTOR_T1 = 15
WORKER_FACTOR_T2_MIN = 300    # 300 <= worker_count < 1000 -> +8
WORKER_FACTOR_T2 = 8
WORKER_FACTOR_T3 = 3          # worker_count < 300 -> +3
TIER_HIGH_MIN = 70
TIER_MEDIUM_MIN = 40
# History-component weights for findings on terminal audits (non-voided).
HISTORY_WEIGHTS = {"ZERO_TOLERANCE": 10, "MAJOR": 4, "MINOR": 1}
HISTORY_COMPONENT_CAP = 100

# --- Audit cadence (PRD §3.2) ---
TIER_BASE_MONTHS = {"HIGH": 6, "MEDIUM": 12, "LOW": 24}
FAILED_ZT_CAP_MONTHS = 3
PROGRAM_VALIDITY_MONTHS = {"BSCI": 24, "SMETA": 12, "RBA": 24, "WRAP": 12}
MIN_INTERVAL_MONTHS = 3
MAX_INTERVAL_MONTHS = 36
FACILITY_GAP_DAYS = 30

# --- Supplier scorecard (PRD §3.6) ---
SCORE_BASE = 100
SCORE_WEIGHTS = {"ZERO_TOLERANCE": 40, "MAJOR": 10, "MINOR": 3}
CRITICAL_GRIEVANCE_DEDUCTION = 5
ESCALATION_PENALTY_PER_FAILURE = 5
ESCALATION_PENALTY_THRESHOLD = 2
TIER_PREFERRED_MIN = 80
TIER_QUALIFIED_MIN = 60
TIER_PROBATION_WATCH_MIN = 40

# --- Recruitment fee reimbursement FX (USD cents per minor unit, PRD §3.8) ---
FX_USD_CENTS_PER_MINOR = {"USD": 1.0, "EUR": 1.08, "INR": 0.012, "BDT": 0.0115}

# --- Remediation due-date offsets in days (PRD §3.4) ---
DUE_DAYS = {"ZERO_TOLERANCE": 30, "MAJOR": 90, "MINOR": 180}

# --- Mutual recognition program minimum scores (PRD §3.9) ---
PROGRAM_MIN_SCORE = {"BSCI": 85, "SMETA": 75, "RBA": 80, "WRAP": 80}
EXTERNAL_AUDIT_FRESHNESS_MONTHS = 12

# --- Pagination defaults (PRD §2.3) ---
DEFAULT_PAGE_LIMIT = 10

# --- Common test timestamps (all at or after the default clock) ---
AUDIT_START = "2026-09-01T00:00:00Z"
AUDIT_END = "2026-09-02T00:00:00Z"
EXTERNAL_AUDIT_DATE_FRESH = "2026-07-01T00:00:00Z"
