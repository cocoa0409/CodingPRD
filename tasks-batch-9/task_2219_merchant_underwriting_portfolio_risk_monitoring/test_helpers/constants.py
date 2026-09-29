"""Numeric constants and thresholds the contract fixes by name.

Every value here is declared literally by the API contract; nothing is
inferred. Tests import these instead of repeating magic numbers so that a
constant that appears in several rules stays a single spelling.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

#: The logical clock's starting value before any test writes to it.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Envelope / pagination
# ---------------------------------------------------------------------------

REQUEST_ID_PREFIX = "req_"
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Reserve requirement determination
# ---------------------------------------------------------------------------

BASE_RESERVE_BPS_BY_BAND = {"A": 50, "B": 500, "C": 900, "D": 1500}
CREDIT_BAND_FLOORS = {"A": 720, "B": 660, "C": 600}
THIN_FILE_UPLIFT_BPS = 300
THIN_FILE_MONTHS_MAX = 6
LAG_UPLIFT_PER_WEEK_BPS = 150
CHARGEBACK_UPLIFT_MULTIPLE = 3
DISPUTE_HORIZON_MULTIPLE = 4
RESERVE_BPS_MIN = 100
RESERVE_BPS_MAX = 2500
CAP_MONTHS = 6
EXPOSURE_CAP_MULTIPLE = 2
ROLLING_CEILING_BPS = 1000

# ---------------------------------------------------------------------------
# Trailing chargeback ratio
# ---------------------------------------------------------------------------

WINDOW_DAYS = 30
EARLY_WARNING_BPS = 65
EXCESSIVE_BPS = 90

# ---------------------------------------------------------------------------
# Settlement / payout
# ---------------------------------------------------------------------------

NORMAL_PAYOUT_LAG_DAYS = 1
DELAYED_PAYOUT_LAG_DAYS = 7
VOLUME_LIMIT_TOLERANCE_BPS = 12500

# ---------------------------------------------------------------------------
# Reserve release eligibility
# ---------------------------------------------------------------------------

ROLLING_RELEASE_LAG_DAYS = 90
CAPPED_RELEASE_LAG_DAYS = 180
RELEASE_COOLING_DAYS = 30

# ---------------------------------------------------------------------------
# Monitoring detectors
# ---------------------------------------------------------------------------

SPIKE_MULTIPLE = 3
CARD_TESTING_MIN_DECLINES = 50
DECLINE_RATIO_BPS_MIN = 4000
CARD_RATIO_BPS_MIN = 8000
MICRO_TICKET_CENTS_MAX = 500
LAUNDERING_SCORE_MIN = 55
BASELINE_DAYS = 30

CARD_TESTING_SEVERITY = 85
CHARGEBACK_SEVERITY_EARLY_WARNING = 60
CHARGEBACK_SEVERITY_EXCESSIVE = 90

# ---------------------------------------------------------------------------
# Remediation programs
# ---------------------------------------------------------------------------

MONTH_DAYS = 30
FAIL_RATIO_BPS = 180
MAX_GRACE_MONTHS = 2
NETWORK_COUNT_MIN = 100

# ---------------------------------------------------------------------------
# Portfolio loss forecast
# ---------------------------------------------------------------------------

LGD_BPS = 6000
RESTRICTED_PD_PENALTY_BPS = 500
PD_TIERS_BY_AMOUNT_RATIO_BPS = {"<65": 100, "65..<90": 300, "90..<180": 900, ">=180": 2000}
ADEQUACY_FULL_BPS = 10000
ADEQUACY_PARTIAL_BPS = 7500
PARTIAL_UPLIFT_BPS = 2500
DEFAULT_STRESS_MULTIPLIER_BPS = 25000
STRESS_PD_CAP_BPS = 10000

# ---------------------------------------------------------------------------
# Appeals
# ---------------------------------------------------------------------------

APPEAL_WINDOW_DAYS = 30

# ---------------------------------------------------------------------------
# Convenient standard application shape used across many scenarios
# ---------------------------------------------------------------------------

STANDARD_MCC_CODE = "5732"
STANDARD_COUNTRY_CODE = "US"
STANDARD_MONTHLY_VOLUME_CENTS = 30_000_000
STANDARD_AVERAGE_TICKET_CENTS = 12_000
STANDARD_CREDIT_SCORE = 700
STANDARD_PRIOR_HISTORY_MONTHS = 24

#: Reserve terms a standard application (credit_score 700, zero lag, 24 months
#: of history, MCC with no category rule, 30 000 000 cents requested volume)
#: resolves to under LAG_WEIGHTED.
STANDARD_RESERVE_PCT_BPS = 500
STANDARD_RESERVE_CAP_CENTS = 2_000_000
STANDARD_RESERVE_TYPE = "ROLLING"
STANDARD_EXPOSURE_CENTS = 1_000_000
