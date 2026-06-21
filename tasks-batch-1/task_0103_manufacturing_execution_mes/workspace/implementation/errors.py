"""Error classes and error-ID constants.

All error_id strings and their HTTP statuses come straight from the PRD
§5 Error Code Catalogue / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    """Carries an error_id, human message, and HTTP status to the handler."""

    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- Error catalogue (id -> http status) -----------------------------------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"               # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                            # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                            # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"               # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"                   # 409
ERR_OPERATION_SEQUENCE_VIOLATION = "ERR_OPERATION_SEQUENCE_VIOLATION"  # 409
ERR_ROUTING_NOT_RELEASED = "ERR_ROUTING_NOT_RELEASED"     # 409
ERR_MACHINE_DOWN = "ERR_MACHINE_DOWN"                     # 409
ERR_TRAVELER_NOT_SIGNED = "ERR_TRAVELER_NOT_SIGNED"       # 409
ERR_RUNLOG_OVERLAP = "ERR_RUNLOG_OVERLAP"                 # 409
ERR_SETUP_BUFFER_CONFLICT = "ERR_SETUP_BUFFER_CONFLICT"   # 409
ERR_BOM_CYCLE = "ERR_BOM_CYCLE"                           # 409
ERR_DUPLICATE_SEQUENCE = "ERR_DUPLICATE_SEQUENCE"         # 409
ERR_SCRAP_QTY_EXCEEDS = "ERR_SCRAP_QTY_EXCEEDS"           # 422
ERR_INSUFFICIENT_LOT_QTY = "ERR_INSUFFICIENT_LOT_QTY"     # 422
ERR_LOT_PRODUCT_MISMATCH = "ERR_LOT_PRODUCT_MISMATCH"     # 422
ERR_STALE_VERSION = "ERR_STALE_VERSION"                   # 412


def unauthenticated(msg="Missing or invalid authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, msg, 401)


def forbidden(msg="The acting role may not perform this operation."):
    return ApiError(ERR_FORBIDDEN, msg, 403)


def not_found(msg="Referenced resource does not exist."):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def invalid_request(msg="Malformed or invalid request."):
    return ApiError(ERR_INVALID_REQUEST, msg, 400)


def invalid_state(msg="Transition not defined from the resource's current state."):
    return ApiError(ERR_INVALID_STATE, msg, 409)
