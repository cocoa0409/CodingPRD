"""Domain thresholds and test defaults for the EAS Compliance API.

Every numeric constant here is stated verbatim in PRD.md; the names are local
shorthands so the tests can read as arithmetic rather than as magic numbers.
"""

# ---------------------------------------------------------------------------
# The logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Station compliance scoring (PRD §3.8) and score bands (PRD §2.10)
# ---------------------------------------------------------------------------
BASE_SCORE = 100.00
COMPLIANT_MIN_SCORE = 90.00
WATCH_MIN_SCORE = 75.00
MISSING_SOURCE_DEDUCTION = 25.00
SILENT_ASSIGNMENT_DEDUCTION = 10.00
REVALIDATION_DEDUCTION = 15.00
OUTAGE_BREACH_DEDUCTION = 10.00
UNFILED_TEST_DEDUCTION = 20.00
CERTIFICATION_WINDOW_DAYS = 365

# ---------------------------------------------------------------------------
# Monitoring silence horizon (PRD §3.3 / §3.8 phase 1)
# ---------------------------------------------------------------------------
SILENCE_MAX_DAYS = 8

# ---------------------------------------------------------------------------
# The two downtime clocks (PRD §3.4)
# ---------------------------------------------------------------------------
CONTINUOUS_BREACH_HOURS = 60
REPAIR_DEADLINE_HOURS = 48
OBLIGATION_WINDOW_START_HOUR = 8
OBLIGATION_WINDOW_END_HOUR = 20

# ---------------------------------------------------------------------------
# Accessibility evaluation (PRD §3.5)
# ---------------------------------------------------------------------------
CRAWL_MIN_SECONDS = 60
TARGET_LUFS = -24.0
LOUDNESS_TOLERANCE_LU = 2.0
CRAWL_POINT_RATE = 0.05
LOUDNESS_POINT_RATE = 0.10
COUPLING_RATE = 0.01
CRAWL_COUPLING_CAP = 3.00
DEFICIENCY_CAP = 8.00
ACCESSIBILITY_PASS_MAX_POINTS = 1.00
CAPTION_PENALTY_POINTS = {
    "NONE": 0.00,
    "CAPTION_SUPPRESSED": 1.50,
    "CRAWL_OVERLAP": 2.00,
}

# ---------------------------------------------------------------------------
# Duplicate suppression windows (PRD §3.5)
# ---------------------------------------------------------------------------
STATION_DEDUP_SECONDS = 900
WEA_MATCH_SECONDS = 1800
WEA_BUFFER_SECONDS = 120

# ---------------------------------------------------------------------------
# Pre-test readiness (PRD §3.6)
# ---------------------------------------------------------------------------
READY_DEVICE_WEIGHT = 40
SOURCE_COVERAGE_WEIGHT = 40
RECENT_ALERT_WEIGHT = 20
RECENT_ALERT_TARGET = 3
RECENT_ALERT_WINDOW_DAYS = 30
READINESS_PASS_MIN = 80.00
READINESS_PREFLIGHT_HOURS = 24

# ---------------------------------------------------------------------------
# Log retention (PRD §3.6)
# ---------------------------------------------------------------------------
RETENTION_BASE_DAYS = 730
RETENTION_NATIONAL_DAYS = 1095
RETENTION_SUSPENDED_EXTRA_DAYS = 365

# ---------------------------------------------------------------------------
# Filing penalties (PRD §3.7)
# ---------------------------------------------------------------------------
FILING_DUE_DAYS = 5
FILING_GRACE_DAYS = 10
PER_ENTRY_LATE_RATE = 0.065
KIND_WEIGHT_RECEIPT = 1.0
KIND_WEIGHT_TRANSMISSION = 1.8
LATE_DAY_POINTS = 0.75
UNCONFIRMED_RELAY_POINTS = 0.50
UNCONFIRMED_RELAY_LOOKBACK_DAYS = 30
PENALTY_CAP = 25.00
STATION_POINT_CEILING = 5.00

# ---------------------------------------------------------------------------
# Inspection response (PRD §3.9)
# ---------------------------------------------------------------------------
INSPECTION_RESPONSE_DAYS = 7
INSPECTION_LATE_DEDUCTION = 20.00
INSPECTION_SATISFIED_MIN = 100.00

# ---------------------------------------------------------------------------
# Enumerations reused across factories and assertions
# ---------------------------------------------------------------------------
SOURCE_TYPES = ["PEP", "NWS", "LP1", "LP2", "SATELLITE", "IPAWS"]
SERVICE_TYPES = ["TV", "FM", "AM", "CABLE"]
DEVICE_ROLES = ["DECODER", "ENCODER", "MONITOR"]
TEST_TYPES = ["WEEKLY", "MONTHLY", "NATIONAL"]
ENTRY_KINDS = ["TRANSMISSION", "RECEIPT"]
RELAY_CLASSES = ["MANDATORY", "OPTIONAL"]
CAPTION_INTERACTIONS = ["NONE", "CAPTION_SUPPRESSED", "CRAWL_OVERLAP"]
DOCUMENT_KINDS = [
    "STATION_LOG",
    "TEST_LOGS",
    "PLAN_COPY",
    "OUTAGE_LOG",
    "ACCESSIBILITY_ATTESTATION",
]

# ---------------------------------------------------------------------------
# Shared test data defaults
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "STATE_CODE": "KS",
    "PLAN_LABEL": "2026-R1",
    "SUCCESSOR_PLAN_LABEL": "2026-R2",
    "CALL_SIGN": "KWEA",
    "SECOND_CALL_SIGN": "KWEB",
    "DUAL_ROLE_CALL_SIGN": "KDUO",
    "SERVICE_TYPE": "TV",
    "MODEL_CODE": "DASDEC-3",
    "DEVICE_ROLE": "DECODER",
    "FIRMWARE_VERSION": "5.2.1",
    "FIPS_CODE": "20173",
    "OTHER_FIPS_CODE": "20209",
}

SOURCE_CALL_SIGNS = {
    "PEP": "WXPEP",
    "NWS": "WXNWS",
    "SATELLITE": "WXSAT",
    "LP1": "WXLP1",
    "LP2": "WXLP2",
    "IPAWS": "WXIPA",
}

# An id that is shaped like a UUID but never minted by the server.
UNRESOLVABLE_UUID = "00000000-0000-4000-8000-000000000000"
