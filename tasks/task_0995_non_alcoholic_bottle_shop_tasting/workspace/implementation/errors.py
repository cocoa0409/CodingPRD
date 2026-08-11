"""Error classes and error ID constants (from SCAFFOLD error catalog)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412
ERR_DUPLICATE = "ERR_DUPLICATE"                      # 409
ERR_AGE_ATTESTATION_REQUIRED = "ERR_AGE_ATTESTATION_REQUIRED"  # 422
ERR_COMPLIANCE_HOLD = "ERR_COMPLIANCE_HOLD"          # 422
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 422
ERR_INVALID_TIME_RANGE = "ERR_INVALID_TIME_RANGE"    # 422
ERR_BOOKING_WINDOW_CLOSED = "ERR_BOOKING_WINDOW_CLOSED"  # 422
ERR_CAPACITY_EXCEEDED = "ERR_CAPACITY_EXCEEDED"      # 422
ERR_DTC_STATE_PROHIBITED = "ERR_DTC_STATE_PROHIBITED"  # 422
ERR_SKU_ABV_STATE_EXCEEDED = "ERR_SKU_ABV_STATE_EXCEEDED"  # 422
ERR_SKU_STATE_PROHIBITED = "ERR_SKU_STATE_PROHIBITED"  # 422
ERR_INSUFFICIENT_POINTS = "ERR_INSUFFICIENT_POINTS"  # 422
ERR_INSUFFICIENT_INVENTORY = "ERR_INSUFFICIENT_INVENTORY"  # 422
ERR_INSUFFICIENT_WALLET = "ERR_INSUFFICIENT_WALLET"  # 422
ERR_SKU_DISCONTINUED = "ERR_SKU_DISCONTINUED"        # 422


def unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="Role not permitted for endpoint per RBAC"):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def not_found(msg="Referenced entity does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Required field missing or wrong type"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def invalid_state(msg="Current state does not permit the requested transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_version(msg="expected version does not match current version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def duplicate(msg="Uniqueness constraint violated"):
    return ApiError(ERR_DUPLICATE, 409, msg)
