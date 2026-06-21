"""API error catalog and exception class. Mirrors §1.6 of the scaffold / §5 of PRD."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (id -> http status). Verbatim from §5 of the PRD.
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_STATE": 409,
    "ERR_ACTION_ALREADY_CLOSED": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_ATTORNEY_NOT_ACTIVE": 422,
    "ERR_FOREIGN_REQUIRES_ATTORNEY": 422,
    "ERR_TEAS_PLUS_REQUIRES_PREAPPROVED": 422,
    "ERR_NO_GOODS_SERVICES": 422,
    "ERR_PROCEEDING_TARGET_INVALID": 422,
    "ERR_OPPOSITION_WINDOW_CLOSED": 422,
    "ERR_RESPONSE_DEADLINE_PASSED": 422,
    "ERR_SOU_NOT_PERMITTED": 422,
    "ERR_MAINTENANCE_WINDOW_NOT_OPEN": 422,
    "ERR_MADRID_COUNTRIES_INVALID": 422,
    "ERR_VALIDATION": 400,
    "ERR_DUPLICATE_BAR_NUMBER": 409,
    "ERR_DUPLICATE_NICE_CLASS": 409,
}


def raise_api(error_id: str, message: str = ""):
    http = ERROR_CATALOG.get(error_id, 500)
    raise APIError(error_id, http, message or error_id)
