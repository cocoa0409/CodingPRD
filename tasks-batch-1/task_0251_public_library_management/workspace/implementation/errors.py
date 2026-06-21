"""Error catalog and custom exception for the Public Library Management API.

Every error_id and HTTP status below is taken verbatim from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    """Carries a machine-readable error_id, human message and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth / existence / request
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                       # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                       # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 400
ERR_VALIDATION_PARAM = "ERR_VALIDATION_PARAM"        # 400
ERR_INVALID_ACTION = "ERR_INVALID_ACTION"            # 400

# State / business gates
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_RESOURCE_NOT_AVAILABLE = "ERR_RESOURCE_NOT_AVAILABLE"  # 409
ERR_CARD_NOT_ACTIVE = "ERR_CARD_NOT_ACTIVE"          # 409
ERR_PATRON_BLOCKED = "ERR_PATRON_BLOCKED"            # 409
ERR_RESERVATION_CONFLICT = "ERR_RESERVATION_CONFLICT"  # 409
ERR_LIMIT_EXCEEDED = "ERR_LIMIT_EXCEEDED"            # 409
ERR_NO_LICENSE_AVAILABLE = "ERR_NO_LICENSE_AVAILABLE"  # 409
ERR_STALE_RESOURCE_VERSION = "ERR_STALE_RESOURCE_VERSION"  # 412

# Specific sub-case codes
ERR_TITLE_WITHDRAWN = "ERR_TITLE_WITHDRAWN"          # 409
ERR_HOLD_NOT_READY = "ERR_HOLD_NOT_READY"            # 409
ERR_PICKUP_EXPIRED = "ERR_PICKUP_EXPIRED"            # 409
ERR_NOT_YET_DUE = "ERR_NOT_YET_DUE"                  # 409
ERR_RENEWAL_LIMIT = "ERR_RENEWAL_LIMIT"              # 409
ERR_RENEWAL_BLOCKED_BY_HOLD = "ERR_RENEWAL_BLOCKED_BY_HOLD"  # 409


# Convenience constructors -------------------------------------------------

def unauthenticated(msg="Missing or unknown authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Caller is not permitted to perform this operation."):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Referenced resource does not exist."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Request body is missing fields or malformed."):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def validation_param(msg="Invalid query or pagination parameter."):
    return ApiError(ERR_VALIDATION_PARAM, 400, msg)


def invalid_action(msg="Unknown action verb."):
    return ApiError(ERR_INVALID_ACTION, 400, msg)


def invalid_state(msg="Resource is not in a state that permits this transition."):
    return ApiError(ERR_INVALID_STATE, 409, msg)
