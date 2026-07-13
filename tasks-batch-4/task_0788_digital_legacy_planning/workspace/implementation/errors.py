"""Error type and HTTP status catalog."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 400,
    "ERR_NOT_FOUND": 404,
    "ERR_FORBIDDEN_SCOPE": 403,
    "ERR_INVALID_STATE": 409,
    "ERR_ACCESS_NOT_RELEASED": 403,
    "ERR_RELEASE_NOT_TRIGGERED": 409,
    "ERR_CROSS_PLAN_REFERENCE": 422,
    "ERR_SHARE_WINDOW_OVERLAP": 409,
    "ERR_DEPUTY_TERM_OVERLAP": 409,
    "ERR_SEAT_LIMIT_REACHED": 409,
    "ERR_ALLOCATION_EXCEEDS_100": 422,
    "ERR_DUPLICATE_APPROVAL": 409,
    "ERR_QUORUM_NOT_MET": 409,
    "ERR_NOTHING_TO_RELEASE": 422,
    "ERR_SUBSCRIPTION_PAST_DUE": 402,
    "ERR_SUBSCRIPTION_REQUIRED": 402,
    "ERR_STALE_VERSION": 412,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_VAULT_ITEM_NOT_FOUND": 404,
    "ERR_DEPUTY_NOT_FOUND": 404,
    "ERR_RELEASE_REQUEST_NOT_FOUND": 404,
    "ERR_DIRECTIVE_NOT_FOUND": 404,
    "ERR_SUBSCRIPTION_NOT_FOUND": 404,
    "ERR_SHARE_NOT_FOUND": 404,
    "ERR_INVALID_LIFE_EVENT": 422,
}
