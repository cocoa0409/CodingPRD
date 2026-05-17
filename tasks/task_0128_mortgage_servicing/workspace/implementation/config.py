"""Server-wide configuration constants."""
import os

PORT = int(os.environ.get("PORT", 10000))
HOST = "0.0.0.0"

# Roles recognised by the system.
ROLES = {
    "Borrower",
    "Servicer",
    "LossMitigationUnderwriter",
    "PmiUnderwriter",
    "ForeclosureAttorney",
    "PlatformAdmin",
}

# Pagination defaults.
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Headers.
HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# Calculation constants.
LATE_FEE_PER_MONTH_CENTS = 5000
LATE_FEE_CAP_CENTS = 25000
PROJECTION_WINDOW_DAYS = 365
CUSHION_MONTHS = 2
SURPLUS_REFUND_FLOOR_CENTS = 5000
AUTO_TERM_LTV_BPS = 7800
BORROWER_REQ_LTV_BPS = 8000
BREACH_GRACE_DAYS = 30
NOI_WINDOW_DAYS = 30
FILING_TO_AUCTION_DAYS = 60
AUCTION_NOTICE_DAYS = 30
REINSTATEMENT_CUTOFF_DAYS = 5
MEDIATION_FAILURE_WINDOW_DAYS = 90
MEDIATION_AUTOFAIL_NOI_DAYS = 60
PMI_HISTORY_MONTHS = 24
DEFAULT_GRACE_DAYS = 120

# Timestamp format: ISO 8601 UTC with three fractional digits + Z.
ISO_FMT = "%Y-%m-%dT%H:%M:%S.{ms}Z"
