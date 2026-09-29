"""Domain thresholds, defaults and rate tables stated by the API contract.

Nothing here is invented: every value is a literal the contract pins, so tests
can reference the named constant instead of repeating a magic number.
"""

from typing import Dict

# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------

#: The clock reads exactly this instant until the clock endpoint is called.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

CLOCK_PATH = "/_clock/set_current_utc"


# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


# --------------------------------------------------------------------------
# Basis points
# --------------------------------------------------------------------------

#: Ten thousand basis points express a whole unit.
BASIS_POINTS_WHOLE = 10000


# --------------------------------------------------------------------------
# Client defaults
# --------------------------------------------------------------------------

DEFAULT_SLA_TURNAROUND_HOURS = 48
MIN_SLA_TURNAROUND_HOURS = 1
MAX_SLA_TURNAROUND_HOURS = 336
DEFAULT_SLA_PENALTY_RATE_CENTS_PER_HOUR = 2500
DEFAULT_SLA_PENALTY_CAP_CENTS = 500000
DEFAULT_CONTROL_TOTAL_TOLERANCE_BP = 5
MIN_CONTROL_TOTAL_TOLERANCE_BP = 0
MAX_CONTROL_TOTAL_TOLERANCE_BP = 10000
DEFAULT_DR_READINESS_REQUIRED = True

MIN_CLIENT_CODE_LENGTH = 3
MAX_CLIENT_CODE_LENGTH = 10
MIN_CLIENT_NAME_LENGTH = 1
MAX_CLIENT_NAME_LENGTH = 120
MAX_ACCOUNT_REF_LENGTH = 40


# --------------------------------------------------------------------------
# Templates and inserts
# --------------------------------------------------------------------------

MIN_SHEETS_PER_DOCUMENT = 1
MAX_SHEETS_PER_DOCUMENT = 200
DEFAULT_COLOR_PAGES_PER_DOCUMENT = 0
DEFAULT_SHEETS_PER_INSERT = 1
DEFAULT_MAIL_CLASS_PREFERENCE = "FIRST_CLASS"


# --------------------------------------------------------------------------
# Address hygiene weights (basis points, summing to 10000)
# --------------------------------------------------------------------------

HYGIENE_WEIGHT_ADDRESS_LINE1_BP = 2500
HYGIENE_WEIGHT_CITY_BP = 1000
HYGIENE_WEIGHT_REGION_BP = 1500
HYGIENE_WEIGHT_POSTAL_CODE_BP = 2200
HYGIENE_WEIGHT_POSTAL_PLUS4_BP = 2800

#: A confidence at or above this reads DELIVERABLE.
HYGIENE_DELIVERABLE_FLOOR = 0.90
#: A confidence at or above this, but below the deliverable floor, reads CORRECTED.
HYGIENE_CORRECTED_FLOOR = 0.65


# --------------------------------------------------------------------------
# Presort
# --------------------------------------------------------------------------

#: A piece with more sheets than this is nonmachinable.
MAX_MACHINABLE_SHEET_COUNT = 12
#: Minimum group size for the five-digit tier.
FIVE_DIGIT_MIN_PIECES = 3
#: Minimum group size for the three-digit tier.
THREE_DIGIT_MIN_PIECES = 2
#: Minimum group size for the area-distribution-centre tier.
AADC_MIN_PIECES = 2
#: Pieces per tray; tray counts round up.
PIECES_PER_TRAY = 4

#: Batch creation order: first class before marketing, then bucket order.
MAIL_CLASS_CREATION_ORDER = ["FIRST_CLASS", "MARKETING"]
PRESORT_BUCKET_CREATION_ORDER = [
    "FIVE_DIGIT",
    "THREE_DIGIT",
    "AADC",
    "MIXED_AADC",
    "NONMACHINABLE",
]


# --------------------------------------------------------------------------
# Press floor
# --------------------------------------------------------------------------

DEFAULT_CHANGEOVER_BUFFER_MINUTES = 30
MIN_CHANGEOVER_BUFFER_MINUTES = 0
MAX_CHANGEOVER_BUFFER_MINUTES = 480

#: A run never occupies fewer minutes than this.
MIN_RUN_MINUTES = 60

#: Press line selector weights and penalty.
SELECTOR_HEADROOM_WEIGHT_BP = 6000
SELECTOR_SPEED_WEIGHT_BP = 4000
SELECTOR_CAPABILITY_SURPLUS_PENALTY = 500

#: Minutes added to the run window end to project job completion.
PROJECTED_COMPLETION_BUFFER_MINUTES = 120


# --------------------------------------------------------------------------
# Induction windows
# --------------------------------------------------------------------------

#: The longest permissible induction window span, inclusive.
MAX_INDUCTION_WINDOW_MINUTES = 1440


# --------------------------------------------------------------------------
# Postage rate table (cents per piece, before sheet surcharge)
# --------------------------------------------------------------------------

POSTAGE_BASE_RATE_CENTS: Dict[str, Dict[str, int]] = {
    "FIRST_CLASS": {
        "FIVE_DIGIT": 53,
        "THREE_DIGIT": 56,
        "AADC": 58,
        "MIXED_AADC": 62,
        "NONMACHINABLE": 88,
    },
    "MARKETING": {
        "FIVE_DIGIT": 27,
        "THREE_DIGIT": 30,
        "AADC": 33,
        "MIXED_AADC": 37,
        "NONMACHINABLE": 55,
    },
}

#: Sheets above this count attract the per-sheet surcharge.
POSTAGE_SURCHARGE_FREE_SHEETS = 3
POSTAGE_SURCHARGE_CENTS_PER_SHEET = 3


def postage_gross_cents(mail_class: str, bucket: str, sheet_count: int) -> int:
    """Gross postage for one piece: base rate plus the sheet surcharge."""
    base = POSTAGE_BASE_RATE_CENTS[mail_class][bucket]
    surcharge = max(0, sheet_count - POSTAGE_SURCHARGE_FREE_SHEETS) * (
        POSTAGE_SURCHARGE_CENTS_PER_SHEET
    )
    return base + surcharge


# --------------------------------------------------------------------------
# SLA and invoicing
# --------------------------------------------------------------------------

#: Severity applied to the penalty rate, in basis points.
SLA_SEVERITY_RUSH_BP = 15000
SLA_SEVERITY_STANDARD_BP = 10000

INVOICE_CENTS_PER_SHEET = 9
INVOICE_CENTS_PER_INSERT_SHEET = 4

#: Volume discount tiers: (subtotal floor in cents, discount in basis points).
INVOICE_DISCOUNT_TIERS = [
    (400, 1200),
    (230, 800),
    (200, 400),
]

#: Expedite uplift in basis points when the job was composed rush.
INVOICE_EXPEDITE_BP = 1500


# --------------------------------------------------------------------------
# Disaster recovery
# --------------------------------------------------------------------------

#: Hours a passing drill keeps readiness valid.
DR_READINESS_VALIDITY_HOURS = 720
#: A replication lag strictly above this reads STALE.
DR_MAX_REPLICATION_LAG_MINUTES = 15


# --------------------------------------------------------------------------
# Scan pipeline
# --------------------------------------------------------------------------

#: The ordered production stages a piece must be read at, one step at a time.
SCAN_STAGE_ORDER = ["PRINT", "INSERT", "INDUCT"]
