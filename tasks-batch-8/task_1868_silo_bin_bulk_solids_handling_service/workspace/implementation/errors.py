"""Error classes and error ID constants, sourced from SCAFFOLD.yaml §1.6."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error ID constants (from SCAFFOLD.yaml §1.6)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_VALIDATION = "ERR_VALIDATION"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_SITE_NOT_FOUND = "ERR_SITE_NOT_FOUND"
ERR_VESSEL_NOT_FOUND = "ERR_VESSEL_NOT_FOUND"
ERR_TECHNICIAN_NOT_FOUND = "ERR_TECHNICIAN_NOT_FOUND"
ERR_TICKET_NOT_FOUND = "ERR_TICKET_NOT_FOUND"
ERR_PERMIT_NOT_FOUND = "ERR_PERMIT_NOT_FOUND"
ERR_ORDER_NOT_FOUND = "ERR_ORDER_NOT_FOUND"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_INVALID_TICKET_STATE = "ERR_INVALID_TICKET_STATE"
ERR_INVALID_ORDER_STATE = "ERR_INVALID_ORDER_STATE"
ERR_INVALID_PERMIT_STATE = "ERR_INVALID_PERMIT_STATE"
ERR_LOCKOUT_NOT_VERIFIED = "ERR_LOCKOUT_NOT_VERIFIED"
ERR_SOD_ISSUER_EQUALS_ENTRANT = "ERR_SOD_ISSUER_EQUALS_ENTRANT"
ERR_INBOUND_DELIVERY_PENDING = "ERR_INBOUND_DELIVERY_PENDING"
ERR_ATMOSPHERE_UNSAFE = "ERR_ATMOSPHERE_UNSAFE"
ERR_ENTRY_PERMIT_REQUIRED = "ERR_ENTRY_PERMIT_REQUIRED"
ERR_WINDOW_IN_PAST = "ERR_WINDOW_IN_PAST"
ERR_TECHNICIAN_DOUBLE_BOOKED = "ERR_TECHNICIAN_DOUBLE_BOOKED"
ERR_VESSEL_DOWNTIME_CONFLICT = "ERR_VESSEL_DOWNTIME_CONFLICT"
ERR_SCALE_OUT_OF_TOLERANCE = "ERR_SCALE_OUT_OF_TOLERANCE"
ERR_INVENTORY_WOULD_GO_NEGATIVE = "ERR_INVENTORY_WOULD_GO_NEGATIVE"
ERR_CREDIT_HOLD = "ERR_CREDIT_HOLD"


def unauthenticated(msg: str = "Missing or invalid X-User-ID / X-User-Role header") -> ApiError:
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def validation(msg: str = "Request body failed validation") -> ApiError:
    return ApiError(ERR_VALIDATION, 400, msg)


def forbidden(msg: str = "Role not permitted for this endpoint") -> ApiError:
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(error_id: str, msg: str = "") -> ApiError:
    return ApiError(error_id, 404, msg or error_id)


def conflict(error_id: str, msg: str = "") -> ApiError:
    return ApiError(error_id, 409, msg or error_id)


def stale_version(msg: str = "expected_vessel_version does not match the vessel's current version") -> ApiError:
    return ApiError(ERR_STALE_VERSION, 412, msg)
