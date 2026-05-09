"""Error definitions and exceptions."""


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error catalog: error_id -> http_status
ERROR_CATALOG = {
    "ERR_AUTH": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_EVENT_FROZEN": 409,
    "ERR_REGISTRATION_CLOSED": 409,
    "ERR_REGISTRATION_BELOW_MIN": 409,
    "ERR_CAPACITY_EXCEEDED": 409,
    "ERR_AVOIDANCE_INFEASIBLE": 422,
    "ERR_INVALID_SCORE": 422,
    "ERR_DUPLICATE_REFEREE_ENTRY": 409,
    "ERR_RESULT_DISAGREEMENT": 409,
    "ERR_REFEREE_NOT_QUALIFIED": 422,
    "ERR_CONFLICT_OF_INTEREST": 422,
    "ERR_REFEREE_TIME_CONFLICT": 409,
    "ERR_PARTICIPANT_TIME_CONFLICT": 409,
    "ERR_ENTRY_FEE_MISMATCH": 422,
    "ERR_TAX_OUT_OF_RANGE": 422,
    "ERR_CHAIN_OF_CUSTODY_BROKEN": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_APPEAL_WINDOW_CLOSED": 422,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_VALIDATION": 422,
}


def err(error_id: str, message: str = "") -> APIError:
    """Construct an APIError using the catalog HTTP status."""
    return APIError(error_id, message or error_id, ERROR_CATALOG[error_id])
