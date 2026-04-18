"""Error catalog for the shared-office API."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


ERRORS = {
    "ERR_MISSING_AUTH": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCED_ENTITY_MISSING": 404,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_RESERVATION_CONFLICT": 409,
    "ERR_INVALID_RESERVATION_STATE": 409,
    "ERR_INVALID_BILL_STATE": 409,
    "ERR_INVALID_LEASE_STATE": 409,
    "ERR_INVALID_VISITOR_STATE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_ACCESS_POSTURE_DENIES": 422,
    "ERR_TENANT_MISMATCH": 422,
    "ERR_INVALID_TIME_WINDOW": 422,
    "ERR_RESERVATION_GRANULARITY": 422,
    "ERR_CAPACITY_EXCEEDED": 422,
    "ERR_HAS_OPEN_RESERVATIONS": 422,
    "ERR_HAS_DRAFT_BILLS": 422,
    "ERR_EMPTY_BILL": 422,
    "ERR_BILL_HAS_OPEN_RESERVATIONS": 422,
    "ERR_INVALID_VISITOR_WINDOW": 422,
    "ERR_PAGINATION_OUT_OF_RANGE": 400,
}


def api_error(error_id: str, message: str = ""):
    http = ERRORS.get(error_id, 400)
    return APIError(error_id, http, message or error_id)
