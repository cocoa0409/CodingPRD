class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (id -> http status), per PRD §5 / scaffold §1.6
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_TEAM_OWNER = ("ERR_NOT_TEAM_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_TRADE_WINDOW_CLOSED = ("ERR_TRADE_WINDOW_CLOSED", 409)
ERR_TEAM_RESTRICTED = ("ERR_TEAM_RESTRICTED", 409)
ERR_DUPLICATE_RESOURCE = ("ERR_DUPLICATE_RESOURCE", 409)
ERR_INVALID_TRADE_ASSETS = ("ERR_INVALID_TRADE_ASSETS", 422)
ERR_ROSTER_LIMIT_EXCEEDED = ("ERR_ROSTER_LIMIT_EXCEEDED", 409)
ERR_PLAYOFF_PRECONDITION = ("ERR_PLAYOFF_PRECONDITION", 409)
ERR_INVALID_FIELD_VALUE = ("ERR_INVALID_FIELD_VALUE", 422)
ERR_CONTRACT_TERM_OVERLAP = ("ERR_CONTRACT_TERM_OVERLAP", 409)
ERR_STINT_OVERLAP = ("ERR_STINT_OVERLAP", 409)
ERR_VALIDATION = ("ERR_VALIDATION", 400)


def err(spec, message=None):
    """spec is one of the (error_id, http_status) tuples above."""
    return ApiError(spec[0], spec[1], message)
