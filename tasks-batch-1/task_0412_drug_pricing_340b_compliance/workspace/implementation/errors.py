"""Error classes and error ID constants for the 340B compliance API."""


class ApiError(Exception):
    """An error that maps to a standard error envelope response."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue (id -> http status). PRD §5.
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_CROSS_ENTITY_MISMATCH": 409,
    "ERR_MEF_NUMBER_REQUIRED": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_CE_NOT_ACTIVE": 409,
    "ERR_GPO_PROHIBITED": 409,
    "ERR_DUPLICATE_DISCOUNT": 409,
    "ERR_NO_CEILING_PRICE": 409,
    "ERR_ASSESSED_UNITS_EXCEED": 422,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_REMIT_EXCEEDS_BALANCE": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_NO_PUBLISHED_CEILING": 409,
    "ERR_REPAYMENT_REQUIRED": 409,
    "ERR_DUPLICATE_HRSA_ID": 409,
    "ERR_DUPLICATE_NDC": 409,
    "ERR_DUPLICATE_ACCUMULATOR": 409,
    "ERR_VALIDATION_PAGINATION": 422,
    "ERR_CP_WINDOW_OVERLAP": 409,
    "ERR_CEILING_QUARTER_OVERLAP": 409,
}


def err(error_id, message=None):
    """Build an ApiError using the catalogue http status."""
    return ApiError(error_id, ERROR_STATUS[error_id], message)
