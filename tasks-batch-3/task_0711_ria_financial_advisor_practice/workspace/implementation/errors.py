"""Error catalogue (PRD §5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error id -> default HTTP status (PRD §5 catalogue)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_IPS_MANDATE_VIOLATION": 422,
    "ERR_CROSS_ENTITY_PRECONDITION": 409,
    "ERR_BILLING_PERIOD_OVERLAP": 409,
    "ERR_REVIEW_DATE_COLLISION": 409,
    "ERR_ALLOCATION_INVALID": 422,
    "ERR_INVALID_PERIOD": 422,
    "ERR_STALE_HOUSEHOLD_VERSION": 412,
    "ERR_INVALID_REQUEST": 400,
    "ERR_FEE_RUN_OPEN": 409,
    "ERR_PORTFOLIO_NOT_PUBLISHED": 422,
    "ERR_NO_APPROVED_IPS": 409,
    "ERR_COMPLIANCE_NOT_DUE": 409,
    "ERR_DUPLICATE_APPROVED_IPS": 409,
    "ERR_GOAL_AMOUNT_INVALID": 422,
    "ERR_PAGINATION_INVALID": 400,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
