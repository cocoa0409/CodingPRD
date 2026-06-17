"""Error catalogue and the ApiError exception (PRD §5, SCAFFOLD Table 6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id -> http_status (PRD §5 Error Code Catalogue)
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_COST_CENTER_FROZEN": 409,
    "ERR_SPAN_LIMIT_EXCEEDED": 409,
    "ERR_HAS_DIRECT_REPORTS": 409,
    "ERR_POSITION_NOT_FUNDED": 409,
    "ERR_POSITION_ALREADY_FILLED": 409,
    "ERR_POSITION_NOT_FILLED": 409,
    "ERR_EMPLOYEE_UNAVAILABLE": 409,
    "ERR_SALARY_OUT_OF_BAND": 409,
    "ERR_INCUMBENCY_OVERLAP": 409,
    "ERR_FREEZE_WINDOW_OVERLAP": 409,
    "ERR_FTE_CAP_EXCEEDED": 409,
    "ERR_BUDGET_EXCEEDED": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
