"""Domain thresholds and constants from the PRD's calculation rules."""

# Logical clock startup default (PRD §2.9): before any client adjustment the
# server-side logical clock reads exactly this instant.
STARTUP_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Remediation SLA table in days by severity (PRD §3.5).
SLA_DAYS = {"CRITICAL": 7, "HIGH": 30, "MEDIUM": 90, "LOW": 180}

# Accelerator: a license-changing fix compresses the SLA to fourteen days from
# detection regardless of severity (PRD §3.5).
LICENSE_CHANGE_SLA_DAYS = 14

# Accelerator: while the product sits BLOCKED the deadline is capped at three
# days from the present moment (PRD §3.5).
BLOCKED_PRODUCT_SLA_DAYS = 3

# License approval validity window in days (PRD §3.4).
APPROVAL_VALIDITY_DAYS = 90

# Release-gate evaluation validity windows in days (PRD §3.7).
GATE_EVALUATION_VALIDITY_DAYS = 30
GATE_BYPASS_VALIDITY_DAYS = 7

# Gate verdict ladder thresholds (PRD §3.7): more than three warnings fail the
# gate; between one and three warnings inclusive yield CONDITIONAL_PASS.
MAX_WARNINGS_FOR_CONDITIONAL = 3

# Release-gate obligations threshold: below one hundred percent fails (PRD §3.7).
OBLIGATIONS_REQUIRED_PCT = 100.0

# Scan finalization requires license scan coverage of at least eighty percent
# (PRD §3.3).
MIN_LICENSE_SCAN_COVERAGE_PCT = 80.0

# Pagination defaults and bounds (PRD §2.3).
PAGE_DEFAULT_LIMIT = 10
PAGE_MAX_LIMIT = 100

# Closed catalogue sizes (PRD §3.2).
KNOWN_LICENSES_COUNT = 18
