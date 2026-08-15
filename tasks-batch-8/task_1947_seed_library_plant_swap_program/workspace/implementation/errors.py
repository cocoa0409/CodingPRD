"""Error classes and error ID constants (from SCAFFOLD.yaml errors catalog)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Error ID constants
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_UNAUTHORIZED_ROLE = "ERR_UNAUTHORIZED_ROLE"      # 403
ERR_SELF_SERVICE_FORBIDDEN = "ERR_SELF_SERVICE_FORBIDDEN"  # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 400
ERR_INVALID_ENUM = "ERR_INVALID_ENUM"                # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"        # 409
ERR_MEMBER_SUSPENDED = "ERR_MEMBER_SUSPENDED"        # 409
ERR_LOT_NOT_ACTIVE = "ERR_LOT_NOT_ACTIVE"            # 409
ERR_EVENT_NOT_INTAKE_OPEN = "ERR_EVENT_NOT_INTAKE_OPEN"  # 409
ERR_EVENT_NOT_CANCELLABLE = "ERR_EVENT_NOT_CANCELLABLE"  # 409
ERR_TEST_NOT_RECORDED = "ERR_TEST_NOT_RECORDED"      # 409
ERR_VIABILITY_OUTCOME_MISMATCH = "ERR_VIABILITY_OUTCOME_MISMATCH"  # 422
ERR_INVASIVE_SPECIES_BLOCKED = "ERR_INVASIVE_SPECIES_BLOCKED"      # 422
ERR_REGION_NOT_APPROVED = "ERR_REGION_NOT_APPROVED"  # 422
ERR_PACKET_NOT_AVAILABLE = "ERR_PACKET_NOT_AVAILABLE"  # 409
ERR_DUPLICATE_LOT_CODE = "ERR_DUPLICATE_LOT_CODE"    # 409
ERR_DUPLICATE_INTAKE_ITEM = "ERR_DUPLICATE_INTAKE_ITEM"  # 409
ERR_EVENT_WINDOW_OVERLAP = "ERR_EVENT_WINDOW_OVERLAP"  # 409
ERR_SESSION_WINDOW_OVERLAP = "ERR_SESSION_WINDOW_OVERLAP"  # 409
ERR_VOLUNTEER_DOUBLE_BOOKED = "ERR_VOLUNTEER_DOUBLE_BOOKED"  # 409
ERR_SESSION_CAPACITY_FULL = "ERR_SESSION_CAPACITY_FULL"  # 422
ERR_BORROW_LIMIT_EXCEEDED = "ERR_BORROW_LIMIT_EXCEEDED"  # 422
ERR_PACK_QUANTITY_EXCEEDS_ALLOCATABLE = "ERR_PACK_QUANTITY_EXCEEDS_ALLOCATABLE"  # 422
ERR_EVENT_CREDIT_CAP_EXCEEDED = "ERR_EVENT_CREDIT_CAP_EXCEEDED"  # 422
ERR_INSUFFICIENT_CREDITS = "ERR_INSUFFICIENT_CREDITS"  # 422
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412


def unauthenticated(msg="Missing or invalid X-User-Role / X-User-ID headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized_role(msg="Role is not permitted for this endpoint."):
    return ApiError(ERR_UNAUTHORIZED_ROLE, 403, msg)


def self_service_forbidden(msg="Self-service ownership check failed."):
    return ApiError(ERR_SELF_SERVICE_FORBIDDEN, 403, msg)


def not_found(msg="Resource not found."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid request body."):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def invalid_enum(msg="Enum value outside its declared set."):
    return ApiError(ERR_INVALID_ENUM, 400, msg)


def invalid_state(msg="Invalid state for this operation."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def already_terminal(msg="Entity is in a terminal state."):
    return ApiError(ERR_ALREADY_TERMINAL, 409, msg)
