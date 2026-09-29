"""Named constants of the leak-detection program, taken from the PRD's formulas.

Every literal below is quoted or arithmetically derived from the PRD text and is
referenced by name from the test suite so that a reader can see which stated
threshold a given expectation belongs to.
"""

# --------------------------------------------------------------------------
# The logical clock (PRD §2.4)
# --------------------------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# The instant every canonical fixture pins the clock to before building state.
FIXTURE_CLOCK_UTC = "2026-08-01T06:05:00Z"

# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# --------------------------------------------------------------------------
# Baseline learning (PRD §3.2)
# --------------------------------------------------------------------------
MIN_LEARNING_SAMPLES = 3
DRIP_FRACTION = 0.02
MIN_DRIP_GPM = 0.05

# --------------------------------------------------------------------------
# Anomaly classification ladder (PRD §3.3)
# --------------------------------------------------------------------------
BURST_FLOW_FACTOR = 1.50
BURST_MIN_DURATION_MINUTES = 3
BURST_MIN_GALLONS = 30
RUNNING_FLOW_FACTOR = 0.40
RUNNING_MIN_DURATION_MINUTES = 20
DRIP_MIN_DURATION_MINUTES = 60
VACATION_SENSITIVITY_MULTIPLIER = 0.50
VACATION_RUNNING_GALLON_CAP = 15

# --------------------------------------------------------------------------
# Severity score (PRD §3.4)
# --------------------------------------------------------------------------
SEVERITY_FLOW_WEIGHT = 0.50
SEVERITY_DURATION_WEIGHT = 0.30
SEVERITY_GALLON_WEIGHT = 0.20
SEVERITY_REFERENCE_FACTOR = 2.00

# --------------------------------------------------------------------------
# Auto-shutoff and the reopen override (PRD §3.4)
# --------------------------------------------------------------------------
OVERRIDE_GRACE_MINUTES = 120

# --------------------------------------------------------------------------
# Uptime coverage (PRD §3.7)
# --------------------------------------------------------------------------
COVERAGE_MINUTES_PER_READING = 120
MIN_OFFLINE_GAP_MINUTES = 60

# --------------------------------------------------------------------------
# Premium credit award (PRD §3.7)
# --------------------------------------------------------------------------
UPTIME_CREDIT_FLOOR_PCT = 95.00
TIER_ELITE_CUT = 99.00
TIER_ELITE_PCT = 0.12
TIER_STRONG_CUT = 97.00
TIER_STRONG_PCT = 0.08
TIER_BASE_CUT = 95.00
TIER_BASE_PCT = 0.05
PERIODS_PER_POLICY_YEAR = 2

# --------------------------------------------------------------------------
# Claim payout award (PRD §3.8)
# --------------------------------------------------------------------------
MITIGATION_WINDOW_MINUTES = 5
WATER_DAMAGE_CAP_CENTS = 500_000
WARRANTY_CAP_CENTS = 150_000
UNMITIGATED_FACTOR = 0.50
POLICY_ANNUAL_PAYOUT_CAP_CENTS = 600_000

# --------------------------------------------------------------------------
# False-positive tuning (PRD §3.6)
# --------------------------------------------------------------------------
TUNING_STEP = 0.20
DRIP_CEILING_GPM = 0.50
MAX_FALSE_POSITIVES_BEFORE_RELEARN = 3
FALSE_POSITIVE_WINDOW_DAYS = 30

# --------------------------------------------------------------------------
# Escalation SLAs (PRD §3.5)
# --------------------------------------------------------------------------
HOMEOWNER_SLA_MINUTES = 15
CONTACT_SLA_MINUTES = 30

# --------------------------------------------------------------------------
# Operational window bounds (PRD §3.1, §3.3, §3.6, §3.9, §3.10)
# --------------------------------------------------------------------------
INSTALL_MIN_STATIC_PSI = 40.0
INSTALL_MAX_STATIC_PSI = 80.0
INSTALL_MAX_DROP_PSI = 2.0
MAX_READING_BACKDATE_HOURS = 24
DUPLICATE_COOLDOWN_MINUTES = 60
MIN_SNOOZE_MINUTES = 30
MAX_SNOOZE_MINUTES = 240
SNOOZE_COOLDOWN_MINUTES = 60
MAX_VACATION_DAYS = 90
TRANSFER_ACCEPT_WINDOW_HOURS = 168
CLAIM_SUBMISSION_WINDOW_DAYS = 30

# --------------------------------------------------------------------------
# Canonical fixture literals
#
# The reference household used throughout the suite: one homeowner, one
# irrigation-capable property, one FLO_SMART_3_4 device whose hold test passes
# well inside the stated pressure band.
# --------------------------------------------------------------------------
TEST_DEFAULTS = {
    "HOMEOWNER_NAME": "Ada Reyes",
    "HOMEOWNER_EMAIL": "ada@example.com",
    "HOMEOWNER_PHONE": "+14155550101",
    "BUYER_NAME": "Ben Ortiz",
    "BUYER_EMAIL": "ben@example.com",
    "BUYER_PHONE": "+14155550202",
    "CONTACT_NAME": "Cal Reyes",
    "CONTACT_PHONE": "+14155550303",
    "ADDRESS_LINE1": "14 Cedar Ln",
    "CITY": "Somerville",
    "STATE_CODE": "MA",
    "POSTAL_CODE": "02143",
    "YEAR_BUILT": 1968,
    "SECOND_ADDRESS_LINE1": "3 Elm St",
    "SECOND_CITY": "Medford",
    "SECOND_POSTAL_CODE": "02155",
    "SECOND_YEAR_BUILT": 1990,
    "SERIAL_NUMBER": "FLO-000001",
    "SECOND_SERIAL_NUMBER": "FLO-000002",
    "MODEL_CODE": "FLO_SMART_3_4",
    "SECOND_MODEL_CODE": "FLO_SMART_1_0",
    "INSTALL_PSI": 62.0,
    "INSTALL_DROP_PSI": 0.8,
    "INSURER_CODE": "AETNA_HOME",
    # An insurer_code runs 2 to 12 uppercase characters, so the rival carrier's
    # code has to fit inside that bound just as the incumbent's does.
    "SECOND_INSURER_CODE": "SENTRYMUTUAL",
    "POLICY_NUMBER": "POL-2225-A",
    "SECOND_POLICY_NUMBER": "POL-2225-B",
    "ANNUAL_PREMIUM_CENTS": 149_900,
    "DEDUCTIBLE_CENTS": 100_000,
}

# The three learning samples that close cycle 1 on the canonical device:
# a quiet sample, a 6.00 gpm peak, then another quiet sample.  Their mean static
# pressure is 60.0 psi and their peak flow is 6.00 gpm, which makes the drip
# threshold max(6.00 * 0.02, 0.05) == 0.12 gpm.
CANONICAL_LEARNING_READINGS = [
    {
        "reading_at": "2026-08-01T00:00:00Z",
        "static_pressure_psi": 60.0,
        "flow_gpm": 0.0,
        "duration_minutes": 0,
        "total_gallons": 0.0,
    },
    {
        "reading_at": "2026-08-01T00:20:00Z",
        "static_pressure_psi": 62.0,
        "flow_gpm": 6.0,
        "duration_minutes": 4,
        "total_gallons": 24.0,
    },
    {
        "reading_at": "2026-08-01T00:40:00Z",
        "static_pressure_psi": 58.0,
        "flow_gpm": 0.0,
        "duration_minutes": 0,
        "total_gallons": 0.0,
    },
]

# The derived baseline of the canonical device.
CANONICAL_BASELINE_STATIC_PSI = 60.0
CANONICAL_BASELINE_PEAK_FLOW_GPM = 6.00
CANONICAL_DRIP_THRESHOLD_GPM = 0.12
CANONICAL_BASELINE_VERSION = 3

# The gates those figures imply under NORMAL monitor mode.
CANONICAL_BURST_FLOW_GATE = 9.00
CANONICAL_BURST_GALLON_GATE = 30.00
CANONICAL_RUNNING_FLOW_GATE = 2.40

# The severity references those figures imply.
CANONICAL_SEVERITY_FLOW_REFERENCE = 18.0
CANONICAL_SEVERITY_DURATION_REFERENCE = 6.0
CANONICAL_SEVERITY_GALLON_REFERENCE = 60.0

# The canonical burst sample: 12.0 gpm for 6 minutes moving 72 gallons while
# static pressure collapses to 30.0 psi.  Against the gates above it is a
# CATASTROPHIC_BURST whose severity_score is 0.833.
CANONICAL_BURST_READING = {
    "static_pressure_psi": 30.0,
    "flow_gpm": 12.0,
    "duration_minutes": 6,
    "total_gallons": 72.0,
}
CANONICAL_BURST_SEVERITY = 0.833

# A drip sample against the same baseline: 0.20 gpm held for a full hour.
CANONICAL_DRIP_READING = {
    "static_pressure_psi": 59.0,
    "flow_gpm": 0.20,
    "duration_minutes": 60,
    "total_gallons": 12.0,
}

# An id that belongs to no row of any entity.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_UUID_ALT = "00000000-0000-0000-0000-0000000000ff"
