"""Error classes and error-id constants.

Every error_id and its HTTP status is taken verbatim from PRD §5 (Error Code
Catalogue) and SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error id -> http status (PRD §5).
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_STATE": 409,
    "ERR_DEPENDENT_STATE_BLOCK": 409,
    "ERR_SURVEY_LOCKED": 409,
    "ERR_INVALID_FIELD": 422,
    "ERR_DECLARED_VALUE_TOO_LOW": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_TRUCK_CAPACITY_EXCEEDED": 409,
    "ERR_CREW_TOO_SMALL": 409,
    "ERR_TRUCK_DOUBLE_BOOKED": 409,
    "ERR_CREW_DOUBLE_BOOKED": 409,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_CLAIM_NOT_ELIGIBLE": 409,
    "ERR_CLAIM_NO_ITEMS": 409,
    "ERR_VALIDATION": 400,
    "ERR_NOT_DELIVERED": 409,
    "ERR_RELEASE_BEFORE_INTAKE": 422,
    "ERR_DEPOSIT_BEFORE_BOOKED": 409,
    "ERR_PAGINATION_INVALID": 422,
    "ERR_DUPLICATE_EMAIL": 409,
    "ERR_DUPLICATE_PLATE": 409,
    "ERR_CANCEL_IN_TRANSIT": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
