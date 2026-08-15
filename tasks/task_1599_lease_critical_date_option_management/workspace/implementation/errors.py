"""Error taxonomy with exact IDs from the scaffold §1.6 error catalog."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# auth
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_SOD_VIOLATION = ("ERR_SOD_VIOLATION", 403)
# existence / shape
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_VALIDATION = ("ERR_VALIDATION", 400)
ERR_FK_SCOPE_VIOLATION = ("ERR_FK_SCOPE_VIOLATION", 422)
# state
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_NEGOTIATION_ALREADY_OPEN = ("ERR_NEGOTIATION_ALREADY_OPEN", 409)
ERR_NOTICE_ALREADY_OPEN = ("ERR_NOTICE_ALREADY_OPEN", 409)
ERR_NOT_IN_HOLDOVER = ("ERR_NOT_IN_HOLDOVER", 409)
# OCC
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
# business temporal / constraint
ERR_NOTICE_WINDOW_CLOSED = ("ERR_NOTICE_WINDOW_CLOSED", 422)
ERR_DISPUTE_WINDOW_CLOSED = ("ERR_DISPUTE_WINDOW_CLOSED", 422)
ERR_TEMPORAL_ORDER = ("ERR_TEMPORAL_ORDER", 422)
ERR_RATE_TERMS_INCOHERENT = ("ERR_RATE_TERMS_INCOHERENT", 422)
ERR_ASSESSMENT_SHAPE = ("ERR_ASSESSMENT_SHAPE", 422)
ERR_LADDER_BREACH = ("ERR_LADDER_BREACH", 422)
ERR_ACK_AFTER_WINDOW = ("ERR_ACK_AFTER_WINDOW", 422)


def raise_error(spec, message: str = ""):
    error_id, status = spec
    raise ApiError(error_id, status, message or error_id)
