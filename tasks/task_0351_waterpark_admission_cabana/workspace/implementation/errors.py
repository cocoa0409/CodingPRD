"""Error classes and error ID constants.

Every error_id and HTTP status is read verbatim from SCAFFOLD §1.6 / PRD §5.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth / existence
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"            # 403
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"    # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404

# Request schema / pagination
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 422
ERR_PAGINATION_INVALID = "ERR_PAGINATION_INVALID"    # 422

# State / OCC
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412

# Business
ERR_GUEST_NOT_BOUND = "ERR_GUEST_NOT_BOUND"          # 409
ERR_WINDOW_TIME_VIOLATION = "ERR_WINDOW_TIME_VIOLATION"  # 409
ERR_CABANA_OVERLAP = "ERR_CABANA_OVERLAP"            # 409
ERR_FREEZE_NOT_ALLOWED = "ERR_FREEZE_NOT_ALLOWED"    # 409
ERR_FREEZE_LIMIT_REACHED = "ERR_FREEZE_LIMIT_REACHED"  # 409
ERR_ORDER_NOT_PAID = "ERR_ORDER_NOT_PAID"            # 409
ERR_WEATHER_HOLD = "ERR_WEATHER_HOLD"                # 409
ERR_WINDOW_CAPACITY_EXCEEDED = "ERR_WINDOW_CAPACITY_EXCEEDED"  # 409
ERR_ALREADY_CONSUMED = "ERR_ALREADY_CONSUMED"        # 409
ERR_RAINCHECK_NOT_ISSUED = "ERR_RAINCHECK_NOT_ISSUED"  # 409
ERR_NO_ACTIVE_POLICY = "ERR_NO_ACTIVE_POLICY"        # 409
ERR_WINDOW_NOT_OPEN = "ERR_WINDOW_NOT_OPEN"          # 409
