"""Domain thresholds and shared literals from the PRD's calculation narratives."""

THRESHOLDS = {
    "OBS_MAX_AGE_MINUTES": 60,          # weather freshness limit at start/resume
    "TRAVEL_BUFFER_MINUTES": 30,        # applicator padded travel buffer
    "PASS_ERROR_PCT_MAX": 5.0,          # calibration verdict boundary (inclusive)
    "CALIBRATION_VALID_DAYS": 180,      # PASS extends validity by 180 days
    "RINSE_FRACTION_PER_TANK": 0.02,    # rinsate per tank load
    "W_MINOR": 2,                       # penalty weight of a MINOR complaint
    "W_MAJOR": 5,                       # penalty weight of a MAJOR complaint
    "ROLLING_DAYS": 365,                # rolling score window
    "RECENCY_DAYS": 90,                 # recency doubler window
    "RECENCY_MULTIPLIER": 2,
    "REVOKE_THRESHOLD": 10,             # rolling score revocation boundary (inclusive)
    "COMPLAINT_WINDOW_DAYS": 30,        # drift complaint filing window
}

# Logical-clock anchors (the clock boots at DEFAULT_CLOCK before any set call).
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"
RX_VALID_FROM = "2026-05-01T00:00:00Z"
RX_VALID_TO = "2026-06-30T23:59:59Z"
WO_SCHEDULED_START = "2026-05-10T08:00:00Z"
WO_SCHEDULED_END = "2026-05-10T11:00:00Z"
WO_STARTED_AT = "2026-05-10T08:00:00Z"
WO_COMPLETED_AT = "2026-05-10T10:30:00Z"
WEATHER_OBSERVED_AT = "2026-05-10T07:30:00Z"
LICENSE_EXPIRES_FAR = "2027-01-01T00:00:00Z"
# Default-clock PASS calibration validity horizon (2026-05-01 + 180 days).
# Wire format per PRD: "ISO 8601 UTC strings with three fractional digits".
CALIBRATION_VALID_UNTIL_DEFAULT = "2026-10-28T00:00:00.000Z"
# REI lockout after the standard two-product completion at 2026-05-10T10:30:00Z
# (max rei_hours 48 -> 2026-05-12T10:30:00Z, rendered with three fractional digits).
REI_UNTIL_STANDARD = "2026-05-12T10:30:00.000Z"

# Pre-computed expected amounts for the standard fixture literals.
EXPECTED = {
    "PROVISIONAL_100AC": 1065000,        # 120000 service + 825000 (P1@1.5) + 120000 (P2@0.4)
    "FINAL_100AC_P1_1_6": 1120000,       # 120000 + 880000 (P1@1.6) + 120000
    "SINGLE_PRODUCT_100AC": 945000,      # 120000 + 825000
    "ROUNDING_ORDER_TOTAL": 15001,       # 10000 + 2503 + 2498 (per-line half-up)
    "RINSATE_100AC_GAL": 24.0,           # ceil(1200/400)=3 loads * 400 * 0.02
    "RINSATE_50AC_GAL": 16.0,            # ceil(600/400)=2 loads * 400 * 0.02
}
