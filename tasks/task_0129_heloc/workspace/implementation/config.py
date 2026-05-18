"""Server-wide configuration constants."""
import os

PORT = int(os.environ.get("PORT", 10000))
HOST = "0.0.0.0"

# Roles recognised by the system (scaffold §1.7).
ROLES = {
    "Originator",
    "Servicer",
    "Borrower",
    "PlatformAdmin",
}

# Pagination defaults (scaffold §1.0 response_envelope.pagination_defaults).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Auth headers (PRD §2.1).
HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# Time-window constants (scaffold §1.3, §1.7).
DAYS_PER_CYCLE = 30
DAYS_PER_YEAR_ACCRUAL = 365
ANNIVERSARY_DAYS = 365
EARLY_CLOSURE_WINDOW_DAYS = 1095
DRAW_PERIOD_DAYS = 3650
DELINQUENCY_DEFAULT_THRESHOLD_DAYS = 90

# Default-trigger priority (PRD §2.9): BANKRUPTCY > SENIOR_LIEN_DEFAULT
# > INSURANCE_LAPSE > DELINQUENCY_90.  Higher value = higher priority.
DEFAULT_TRIGGER_PRIORITY = {
    "BANKRUPTCY": 4,
    "SENIOR_LIEN_DEFAULT": 3,
    "INSURANCE_LAPSE": 2,
    "DELINQUENCY_90": 1,
}

# Endpoints exclusive to the Servicer-side of the segregation-of-duties
# rule (scaffold validation priority 5). Originator may not perform any
# of these even if otherwise auth'd; the response is the more specific
# ERR_SEGREGATION_OF_DUTIES instead of ERR_FORBIDDEN.
SERVICER_EXCLUSIVE_ENDPOINTS = {
    "POST /helocs/{id}/close",
    "POST /helocs/{id}/rate-resets",
    "POST /properties/{id}/insurance-events",
    "POST /senior-liens/{id}/default-events",
    "POST /borrowers/{id}/bankruptcy-events",
    "POST /_sweep/billing-cycle",
    "POST /_sweep/annual-fees",
    "POST /_clock/advance",
}
