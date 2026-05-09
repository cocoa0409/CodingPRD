"""Error catalog for the public rental housing API.

Every error_id is mapped to its HTTP status per the PRD §5 / SCAFFOLD.yaml §1.6.
"""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


# Authoritative error -> HTTP status map taken from PRD §5 / SCAFFOLD.yaml errors[]
ERRORS = {
    # Auth & headers
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,

    # Existence
    "ERR_NOT_FOUND": 404,
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_HOUSING_UNIT_NOT_FOUND": 404,
    "ERR_ALLOCATION_NOT_FOUND": 404,
    "ERR_OBJECTION_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_RENT_REDUCTION_NOT_FOUND": 404,
    "ERR_ANNUAL_REVIEW_NOT_FOUND": 404,
    "ERR_SYNC_EVENT_NOT_FOUND": 404,

    # Input validation
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_LEASE_TERM": 400,
    "ERR_BEDROOM_COUNT_TYPE_MISMATCH": 400,

    # Concurrency
    "ERR_VERSION_MISMATCH": 409,
    "ERR_DUPLICATE_ACTIVE_APPLICATION": 409,

    # State - Application
    "ERR_APPLICATION_NOT_IN_DRAFT": 409,
    "ERR_APPLICATION_NOT_UNDER_REVIEW": 409,
    "ERR_APPLICATION_NOT_SCORED": 409,
    "ERR_APPLICATION_NOT_OCCUPIED": 409,
    "ERR_APPLICATION_NOT_EXIT_PENDING": 409,

    # State - Allocation
    "ERR_ALLOCATION_NOT_PUBLISHED": 409,
    "ERR_ALLOCATION_NOT_CONFIRMED": 409,
    "ERR_OBJECTION_NOT_PENDING": 409,

    # State - Contract
    "ERR_CONTRACT_NOT_IN_DRAFT": 409,
    "ERR_CONTRACT_NOT_DEPOSIT_PAID": 409,
    "ERR_CONTRACT_NOT_SIGNED": 409,

    # State - RentReduction
    "ERR_RENT_REDUCTION_NOT_SUBMITTED": 409,
    "ERR_RENT_REDUCTION_NOT_IN_PRIMARY": 409,
    "ERR_RENT_REDUCTION_NOT_IN_SECONDARY": 409,
    "ERR_RENT_REDUCTION_NOT_REJECTABLE": 409,
    "ERR_RENT_REDUCTION_NOT_REJECTED": 409,

    # State - AnnualReview
    "ERR_ANNUAL_REVIEW_NOT_OPEN": 409,
    "ERR_ANNUAL_REVIEW_ALREADY_OPEN": 409,

    # Business referential / cross-data
    "ERR_HOUSEHOLD_REGISTRATION_MISMATCH": 409,
    "ERR_IDENTITY_VERIFICATION_FAILED": 409,
    "ERR_INCOME_OVER_THRESHOLD": 409,
    "ERR_ASSETS_OVER_THRESHOLD": 409,
    "ERR_EXISTING_HOUSING_DETECTED": 409,

    # Business temporal
    "ERR_NOTICE_PERIOD_NOT_ELAPSED": 409,
    "ERR_NOTICE_PERIOD_CLOSED": 409,
    "ERR_GRACE_PERIOD_NOT_ELAPSED": 409,
    "ERR_LEASE_NOT_STARTED": 409,
    "ERR_OVERLAPPING_RENT_REDUCTION": 409,

    # Business fiscal
    "ERR_DEPOSIT_AMOUNT_MISMATCH": 402,

    # Business constraint / safety
    "ERR_UNIT_NOT_AVAILABLE": 409,
    "ERR_NO_ELIGIBLE_APPLICATION": 409,
    "ERR_SEGREGATION_OF_DUTIES_VIOLATION": 403,
}


def api_error(error_id: str, message: str = "") -> APIError:
    http = ERRORS.get(error_id, 400)
    return APIError(error_id, http, message or error_id)
