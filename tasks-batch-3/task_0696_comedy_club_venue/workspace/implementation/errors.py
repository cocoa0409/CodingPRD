"""Error classes and error-id constants (from PRD §5 / scaffold §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- auth / existence ---
ERR_MISSING_AUTH = "ERR_MISSING_AUTH"            # 401
ERR_ROLE_FORBIDDEN = "ERR_ROLE_FORBIDDEN"        # 403
ERR_NOT_OWNER = "ERR_NOT_OWNER"                  # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                  # 404
# --- request shape ---
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"      # 422
ERR_CROSS_SHOW_REFERENCE = "ERR_CROSS_SHOW_REFERENCE"  # 409
# --- state ---
ERR_INVALID_STATE = "ERR_INVALID_STATE"          # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"          # 412
# --- temporal ---
ERR_TIMING_NOT_ALLOWED = "ERR_TIMING_NOT_ALLOWED"  # 409
ERR_SHOW_TIME_CONFLICT = "ERR_SHOW_TIME_CONFLICT"  # 409
# --- posture / safety ---
ERR_POSTURE_BLOCKED = "ERR_POSTURE_BLOCKED"      # 409
# --- contract ---
ERR_COUNTER_LIMIT_REACHED = "ERR_COUNTER_LIMIT_REACHED"  # 409
# --- seating / quota ---
ERR_SECTION_SOLD_OUT = "ERR_SECTION_SOLD_OUT"    # 409
ERR_TABLE_TOO_SMALL = "ERR_TABLE_TOO_SMALL"      # 409
ERR_TABLE_UNAVAILABLE = "ERR_TABLE_UNAVAILABLE"  # 409
ERR_WRONG_SECTION_KIND = "ERR_WRONG_SECTION_KIND"  # 409
ERR_SERVER_OVERLOADED = "ERR_SERVER_OVERLOADED"  # 409
ERR_NO_SERVER_ASSIGNED = "ERR_NO_SERVER_ASSIGNED"  # 409
# --- settlement / fiscal ---
ERR_MINIMUM_NOT_MET = "ERR_MINIMUM_NOT_MET"      # 409
ERR_SETTLEMENT_EXISTS = "ERR_SETTLEMENT_EXISTS"  # 409
ERR_SHOW_NOT_ENDED = "ERR_SHOW_NOT_ENDED"        # 409
# --- guest list ---
ERR_GUEST_LIST_NOT_LISTED = "ERR_GUEST_LIST_NOT_LISTED"  # 409
# --- pagination ---
ERR_INVALID_PAGINATION = "ERR_INVALID_PAGINATION"  # 422


def not_found():
    return ApiError(ERR_NOT_FOUND, 404, "Referenced resource does not exist")


def invalid_request(msg="Invalid request"):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def invalid_state(msg="Resource not in a valid state for this operation"):
    return ApiError(ERR_INVALID_STATE, 409, msg)
