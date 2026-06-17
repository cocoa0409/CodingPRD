"""Error catalog (PRD §5) — error_id -> HTTP status, plus the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = ERROR_STATUS[error_id]


# PRD §5 Error Code Catalogue — verbatim error_id -> HTTP status mapping.
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_FARM_NOT_OPEN": 409,
    "ERR_WINDOW_TIME_INVALID": 422,
    "ERR_EMPTY_PARTY": 422,
    "ERR_WINDOW_SOLD_OUT": 409,
    "ERR_WINDOW_VERSION_STALE": 412,
    "ERR_WAIVER_INCOMPLETE": 422,
    "ERR_GUARDIAN_REQUIRED": 422,
    "ERR_PASS_NOT_VALID": 422,
    "ERR_GROUP_WINDOW_MISMATCH": 422,
    "ERR_PASS_ALREADY_REVOKED": 409,
    "ERR_PUMPKIN_ALREADY_WEIGHED": 409,
    "ERR_CHECKOUT_NOT_FINALIZED": 409,
    "ERR_GROUP_NOT_REVISABLE": 409,
    "ERR_NO_ACTIVE_POLICY": 409,
    "ERR_POLICY_ALREADY_ACTIVE": 409,
    "ERR_WINDOW_CANCELLED": 409,
    "ERR_WINDOW_OVERLAP": 409,
    "ERR_PASS_OVERLAP": 409,
}
