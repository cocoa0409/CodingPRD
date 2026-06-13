"""Error catalogue and the ApiError exception type.

Every error_id and HTTP status comes directly from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- error_id / http_status constants (PRD §5) ---
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_REFERENTIAL_MISMATCH = ("ERR_REFERENTIAL_MISMATCH", 409)
ERR_TEMPORAL_CONFLICT = ("ERR_TEMPORAL_CONFLICT", 409)
ERR_ACCOUNT_NOT_ELIGIBLE = ("ERR_ACCOUNT_NOT_ELIGIBLE", 409)
ERR_INSUFFICIENT_CREDIT = ("ERR_INSUFFICIENT_CREDIT", 409)
ERR_DUPLICATE_RESOURCE = ("ERR_DUPLICATE_RESOURCE", 409)
ERR_PAYOFF_NOT_REVERSIBLE = ("ERR_PAYOFF_NOT_REVERSIBLE", 409)
ERR_VALIDATION_AMOUNT = ("ERR_VALIDATION_AMOUNT", 422)


def err(pair, message=None):
    """Build an ApiError from one of the (id, status) constants above."""
    return ApiError(pair[0], pair[1], message)
