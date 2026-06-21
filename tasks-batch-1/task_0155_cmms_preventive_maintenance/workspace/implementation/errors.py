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
ERR_FORBIDDEN = "ERR_FORBIDDEN"                           # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                           # 404
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"       # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"               # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"                   # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                   # 412
ERR_SKILL_INSUFFICIENT = "ERR_SKILL_INSUFFICIENT"         # 422
ERR_SCHEDULE_CONFIG_INVALID = "ERR_SCHEDULE_CONFIG_INVALID"  # 422
ERR_METER_NOT_MONOTONIC = "ERR_METER_NOT_MONOTONIC"       # 422
ERR_DOWNTIME_OVERLAP = "ERR_DOWNTIME_OVERLAP"             # 409
ERR_DOWNTIME_INTERVAL_INVALID = "ERR_DOWNTIME_INTERVAL_INVALID"  # 422
ERR_INSUFFICIENT_STOCK = "ERR_INSUFFICIENT_STOCK"         # 422
ERR_BACKLOG_EXCEEDED = "ERR_BACKLOG_EXCEEDED"             # 422
ERR_WARRANTY_EXPIRED = "ERR_WARRANTY_EXPIRED"             # 422
ERR_PARTS_NOT_COMMITTED = "ERR_PARTS_NOT_COMMITTED"       # 409
ERR_DOWNTIME_OPEN = "ERR_DOWNTIME_OPEN"                   # 409
ERR_DUPLICATE_SKU = "ERR_DUPLICATE_SKU"                   # 409
ERR_ASSET_BUSY = "ERR_ASSET_BUSY"                         # 409
ERR_PM_NOT_DUE = "ERR_PM_NOT_DUE"                         # 409
ERR_TECH_DOUBLE_BOOKED = "ERR_TECH_DOUBLE_BOOKED"         # 409
ERR_VALIDATION = "ERR_VALIDATION"                         # 400


def unauthenticated(msg="Missing or unrecognized X-User-Role header."):
    return ApiError(ERR_UNAUTHENTICATED, msg, 401)


def forbidden(msg="The acting role may not perform this operation."):
    return ApiError(ERR_FORBIDDEN, msg, 403)


def not_found(msg="A resource id in the path does not exist."):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def reference_not_found(msg="A referenced resource does not exist."):
    return ApiError(ERR_REFERENCE_NOT_FOUND, msg, 404)


def invalid_request(msg="Malformed or invalid request body."):
    return ApiError(ERR_INVALID_REQUEST, msg, 400)


def invalid_state(msg="Transition not defined from the resource's current state."):
    return ApiError(ERR_INVALID_STATE, msg, 409)


def stale_version(msg="The expected version does not match the parent's current version."):
    return ApiError(ERR_STALE_VERSION, msg, 412)


def validation(msg="Field-level validation failed."):
    return ApiError(ERR_VALIDATION, msg, 400)
