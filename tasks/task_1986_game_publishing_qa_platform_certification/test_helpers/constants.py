"""Domain thresholds and constants — numeric rules stated in the PRD."""

# Logical clock fixed startup default (PRD §2.4).
DEFAULT_CLOCK_START = "2026-08-01T00:00:00Z"  # a Saturday

# Submission fee (PRD §3.5): base and per-platform cap, integer cents.
BASE_FEE_CENTS = {"PS5": 120000, "XSX": 120000, "SWITCH2": 90000, "PC": 60000}
FEE_CAP_CENTS = {"PS5": 250000, "XSX": 250000, "SWITCH2": 200000, "PC": 150000}
ROUND1_MULT = 1.00
ROUND2_MULT = 0.50
ROUND3_PLUS_MULT = 0.25
EXPEDITED_MULT = 1.75
WEEKEND_MULT = 1.20

# Vendor invoice settlement (PRD §3.3).
OT_MULTIPLIER = 1.5
ESCAPE_CLAWBACK_PCT = 10
ESCAPE_CLAWBACK_CAP_PCT = 50

# Bug triage SLA hours by severity (PRD §3.4); TRIVIAL carries no SLA.
SLA_HOURS = {"BLOCKER": 24, "CRITICAL": 72, "MAJOR": 168, "MINOR": 720}

# Release-window demand pricing (PRD §3.9).
WINDOW_RATE_CENTS_PER_HOUR = 5000
TIER_MEDIUM_MIN_HOURS = 40
TIER_HIGH_MIN_HOURS = 100
TIER_LOW_MULT = 1.00
TIER_MEDIUM_MULT = 1.25
TIER_HIGH_MULT = 1.50

# Hotfix expedited certification (PRD §3.9).
HOTFIX_CERT_FEE_CENTS = 50000
HOTFIX_QUOTA_MAX = 2
QUOTA_WINDOW_DAYS = 30
AUTO_EMBARGO_ROLLBACK_THRESHOLD = 2

# Age-rating filings (PRD §3.8).
TERRITORY_FEE_CENTS = {"ESRB": 40000, "PEGI": 25000, "CERO": 18000, "USK": 15000}
BUNDLE_MIN_OTHER_FILINGS = 2
BUNDLE_DISCOUNT = 0.10

# Platform -> age-rating territory mapping (PRD §3.8).
PLATFORM_TERRITORY = {"PS5": "ESRB", "XSX": "ESRB", "SWITCH2": "CERO", "PC": "USK"}

# Localization lock thresholds (PRD §3.8).
LOCK_TEXT_COVERAGE_MIN = 98.00
LOCK_AUDIO_COVERAGE_MIN = 95.00

# Per-platform requirements catalog (PRD §3.6):
# (requirement_code, severity, auto_verifiable).
TRC_CATALOG = {
    "PS5": [
        ("TRC-PS-01", "REQUIRED", True),
        ("TRC-PS-02", "REQUIRED", False),
        ("TRC-PS-03", "REQUIRED", False),
        ("TRC-PS-04", "RECOMMENDED", False),
    ],
    "XSX": [
        ("XR-XB-01", "REQUIRED", True),
        ("XR-XB-02", "REQUIRED", False),
        ("XR-XB-03", "RECOMMENDED", False),
    ],
    "SWITCH2": [
        ("LOT-NS-01", "REQUIRED", False),
        ("LOT-NS-02", "REQUIRED", False),
    ],
    "PC": [
        ("ST-PC-01", "REQUIRED", True),
        ("ST-PC-02", "RECOMMENDED", False),
    ],
}

# Verification results that drive a freshly seeded checklist to fully
# pass-equivalent (REQUIRED items PASSED, RECOMMENDED items NA).
CHECKLIST_PASS_SEQUENCE = {
    platform: [(code, "PASSED") if severity == "REQUIRED" else (code, "NA")
               for code, severity, _ in items]
    for platform, items in TRC_CATALOG.items()
}

TEST_DEFAULTS = {
    "TITLE_BUDGET_CENTS": 1_000_000,
    "VENDOR_CAPACITY_HOURS": 40,
    "VENDOR_RATE_CENTS": 5000,
    "TARGET_LAUNCH_DATE": "2026-11-01",
    "WEEK_START": "2026-08-03",  # a Monday
}
