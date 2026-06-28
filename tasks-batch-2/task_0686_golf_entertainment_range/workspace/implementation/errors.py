"""Error classes and error-id constants.

Every error_id / http_status pair is taken verbatim from SCAFFOLD.yaml §1.6
and PRD §5. Do not invent new error ids.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (PRD §5) -------------------------------------------------------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"            # 403
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"    # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_BAY_WINDOW_CONFLICT = "ERR_BAY_WINDOW_CONFLICT"  # 409
ERR_BAY_UNAVAILABLE = "ERR_BAY_UNAVAILABLE"          # 409
ERR_NO_BAY_AVAILABLE = "ERR_NO_BAY_AVAILABLE"        # 409
ERR_NOT_QUEUE_HEAD = "ERR_NOT_QUEUE_HEAD"            # 409
ERR_CARD_DEPLETED = "ERR_CARD_DEPLETED"              # 409
ERR_INSUFFICIENT_FUNDS = "ERR_INSUFFICIENT_FUNDS"    # 402
ERR_HOLD_EXPIRED = "ERR_HOLD_EXPIRED"                # 409
ERR_FBTAB_NOT_CLOSED = "ERR_FBTAB_NOT_CLOSED"        # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412
ERR_VALIDATION_RANGE = "ERR_VALIDATION_RANGE"        # 422
ERR_DUPLICATE_EMAIL = "ERR_DUPLICATE_EMAIL"          # 409
ERR_PAGINATION_INVALID = "ERR_PAGINATION_INVALID"    # 400


_STATUS = {
    ERR_UNAUTHENTICATED: 401,
    ERR_FORBIDDEN_ROLE: 403,
    ERR_NOT_RESOURCE_OWNER: 403,
    ERR_NOT_FOUND: 404,
    ERR_INVALID_REQUEST: 400,
    ERR_INVALID_STATE: 409,
    ERR_BAY_WINDOW_CONFLICT: 409,
    ERR_BAY_UNAVAILABLE: 409,
    ERR_NO_BAY_AVAILABLE: 409,
    ERR_NOT_QUEUE_HEAD: 409,
    ERR_CARD_DEPLETED: 409,
    ERR_INSUFFICIENT_FUNDS: 402,
    ERR_HOLD_EXPIRED: 409,
    ERR_FBTAB_NOT_CLOSED: 409,
    ERR_STALE_VERSION: 412,
    ERR_VALIDATION_RANGE: 422,
    ERR_DUPLICATE_EMAIL: 409,
    ERR_PAGINATION_INVALID: 400,
}


def raise_err(error_id, message=None):
    raise ApiError(error_id, _STATUS[error_id], message)
