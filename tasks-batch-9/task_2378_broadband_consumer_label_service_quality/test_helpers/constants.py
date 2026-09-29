"""Named constants taken from the PRD: thresholds, tiers, clock anchors.

No magic numbers belong in test bodies; every threshold the PRD names lives here.
"""

# ---------------------------------------------------------------------------
# Validation thresholds (PRD §2.9, §2.11, §3.4, §3.8)
# ---------------------------------------------------------------------------

SUBSTANTIATION_MIN_MARGIN = 0.80
PROBE_COOLDOWN_MINUTES = 60
NOTICE_MIN_DAYS = 30
COMPLAINT_SLA_DAYS = 30
REOPEN_WINDOW_DAYS = 30
MAX_REOPENS = 2

# ---------------------------------------------------------------------------
# Calculation constants (PRD §2.7, §2.10, §3.5, §3.8)
# ---------------------------------------------------------------------------

DISCOUNT_MONTHLY_CAP_CENTS = 3000
PROMO_DISCLOSURE_MONTHS = 12
POSTURE_FREEZE_UPHELD_COUNT = 3
PHASE_MONTH_SECONDS = 2592000
LATENCY_TOLERANCE_MS = 5
RELIABILITY_WINDOW_DAYS = 30
SEVERE_RATIO = 0.50
MODERATE_RATIO = 0.25
CREDIT_WINDOW_DAYS = 30
CREDIT_FLOOR_CENTS = 500
REMEDIATION_AUDIT_THRESHOLD = 2

FLAT_TIER_CENTS = {
    "NONE": 0,
    "MINOR": 1000,
    "MODERATE": 2500,
    "SEVERE": 5000,
}

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

CLOCK_PATH = "/_clock/set_current_utc"
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

#: Anchor used by the shared reference scenario: after the measurement windows
#: of August 2026 have closed, on the day the reference label takes effect.
REFERENCE_NOW = "2026-09-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination defaults (PRD §2.6)
# ---------------------------------------------------------------------------

DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# ---------------------------------------------------------------------------
# Reference measurement window used across the substantiation scenarios.
# ---------------------------------------------------------------------------

REFERENCE_WINDOW_START = "2026-08-03T00:00:00Z"
REFERENCE_WINDOW_END = "2026-08-09T23:00:00Z"

#: Six samples of the reference run: four fall inside the 19:00-23:00 UTC peak
#: band declared by the reference methodology, two fall outside it.
REFERENCE_SAMPLES = [
    {
        "observed_at": "2026-08-03T19:10:00Z",
        "download_mbps": 210,
        "upload_mbps": 100,
        "latency_ms": 42,
    },
    {
        "observed_at": "2026-08-04T21:30:00Z",
        "download_mbps": 238,
        "upload_mbps": 112,
        "latency_ms": 24,
    },
    {
        "observed_at": "2026-08-05T20:40:00Z",
        "download_mbps": 242,
        "upload_mbps": 118,
        "latency_ms": 22,
    },
    {
        "observed_at": "2026-08-08T19:45:00Z",
        "download_mbps": 290,
        "upload_mbps": 130,
        "latency_ms": 18,
    },
    {
        "observed_at": "2026-08-05T14:30:00Z",
        "download_mbps": 295,
        "upload_mbps": 145,
        "latency_ms": 14,
    },
    {
        "observed_at": "2026-08-06T02:40:00Z",
        "download_mbps": 306,
        "upload_mbps": 155,
        "latency_ms": 55,
    },
]

# Pre-computed expectations for the reference plan (advertised 300/140 Mbps).
PEAK_HOUR_MEDIAN_POOLED_COUNT = 4
PEAK_HOUR_MEDIAN_TYPICAL_DOWNLOAD = 240.00
PEAK_HOUR_MEDIAN_TYPICAL_UPLOAD = 115.00
PEAK_HOUR_MEDIAN_TYPICAL_LATENCY = 42
PEAK_HOUR_MEDIAN_DOWNLOAD_MARGIN = 0.8000
PEAK_HOUR_MEDIAN_UPLOAD_MARGIN = 0.8214

ALL_HOUR_P20_POOLED_COUNT = 6
ALL_HOUR_P20_TYPICAL_DOWNLOAD = 238.00
ALL_HOUR_P20_TYPICAL_UPLOAD = 112.00
ALL_HOUR_P20_TYPICAL_LATENCY = 55
ALL_HOUR_P20_DOWNLOAD_MARGIN = 0.7933
ALL_HOUR_P20_UPLOAD_MARGIN = 0.8000
