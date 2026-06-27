"""Error classes and error-id constants from the scaffold error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (Table 1.6). http status per scaffold.
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER = ("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400)
ERR_FORBIDDEN_FOR_ROLE = ("ERR_FORBIDDEN_FOR_ROLE", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_VALIDATION_ALREADY_SENT = ("ERR_VALIDATION_ALREADY_SENT", 409)
ERR_CEASE_COMMUNICATION = ("ERR_CEASE_COMMUNICATION", 409)
ERR_VALIDATION_HOLD = ("ERR_VALIDATION_HOLD", 409)
ERR_OUTSIDE_CALL_WINDOW = ("ERR_OUTSIDE_CALL_WINDOW", 409)
ERR_POST_CONVERSATION_COOLDOWN = ("ERR_POST_CONVERSATION_COOLDOWN", 409)
ERR_CADENCE_EXCEEDED = ("ERR_CADENCE_EXCEEDED", 409)
ERR_TIME_BARRED = ("ERR_TIME_BARRED", 409)
ERR_SETTLEMENT_BELOW_FLOOR = ("ERR_SETTLEMENT_BELOW_FLOOR", 409)
ERR_ACCOUNT_NOT_WORKABLE = ("ERR_ACCOUNT_NOT_WORKABLE", 409)
ERR_FURNISH_BLOCKED = ("ERR_FURNISH_BLOCKED", 409)
ERR_ARRANGEMENT_NOT_ACCEPTED = ("ERR_ARRANGEMENT_NOT_ACCEPTED", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)


def fail(spec, message=None):
    """Raise an ApiError from a (error_id, http_status) tuple."""
    error_id, http = spec
    raise ApiError(error_id, http, message)
