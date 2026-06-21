"""Error classes and error-id constants (from SCAFFOLD §1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth / generic
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"            # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 422
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409

# OCC
ERR_STALE_FLOOR_VERSION = "ERR_STALE_FLOOR_VERSION"  # 412
ERR_STALE_VISIT_VERSION = "ERR_STALE_VISIT_VERSION"  # 412

# Business safety / referential / temporal / capacity
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 409
ERR_ID_NOT_SCANNED = "ERR_ID_NOT_SCANNED"               # 409
ERR_AGREEMENT_NOT_SIGNED = "ERR_AGREEMENT_NOT_SIGNED"   # 409
ERR_VISIT_NOT_SIGNABLE = "ERR_VISIT_NOT_SIGNABLE"       # 409
ERR_PASS_NOT_ACTIVE = "ERR_PASS_NOT_ACTIVE"             # 409
ERR_PASS_WINDOW = "ERR_PASS_WINDOW"                     # 409
ERR_ROOM_CONFLICT = "ERR_ROOM_CONFLICT"                 # 409
ERR_PARKING_CONFLICT = "ERR_PARKING_CONFLICT"           # 409
ERR_FLOOR_AT_CAPACITY = "ERR_FLOOR_AT_CAPACITY"         # 409
ERR_NO_BADGE_AVAILABLE = "ERR_NO_BADGE_AVAILABLE"       # 409


def err(error_id, http_status, message=None):
    return ApiError(error_id, http_status, message)
