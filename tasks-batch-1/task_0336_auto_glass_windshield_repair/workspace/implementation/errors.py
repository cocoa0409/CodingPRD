"""Error catalog and the ApiError exception carrying error_id + http_status.

Error IDs and HTTP statuses are taken verbatim from PRD section 5 / scaffold 1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- auth ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                      # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                                  # 403

# --- existence / shape ---
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                  # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                      # 400

# --- state ---
ERR_INVALID_STATE = "ERR_INVALID_STATE"                          # 409

# --- OCC ---
ERR_STALE_WORK_ORDER_VERSION = "ERR_STALE_WORK_ORDER_VERSION"    # 412

# --- business safety / scheduling / referential / fiscal ---
ERR_ADAS_PART_INCOMPATIBLE = "ERR_ADAS_PART_INCOMPATIBLE"        # 422
ERR_MOBILE_NOT_ELIGIBLE = "ERR_MOBILE_NOT_ELIGIBLE"             # 422
ERR_TECH_NOT_CERTIFIED = "ERR_TECH_NOT_CERTIFIED"               # 422
ERR_CURE_NOT_ELAPSED = "ERR_CURE_NOT_ELAPSED"                   # 422
ERR_TECHNICIAN_DOUBLE_BOOKED = "ERR_TECHNICIAN_DOUBLE_BOOKED"   # 409
ERR_BAY_DOUBLE_BOOKED = "ERR_BAY_DOUBLE_BOOKED"                 # 409
ERR_MOBILE_TECH_UNAVAILABLE = "ERR_MOBILE_TECH_UNAVAILABLE"     # 422
ERR_PART_NOT_READY = "ERR_PART_NOT_READY"                       # 409
ERR_OVERPAYMENT = "ERR_OVERPAYMENT"                             # 422
ERR_BALANCE_UNPAID = "ERR_BALANCE_UNPAID"                       # 402
ERR_DUPLICATE = "ERR_DUPLICATE"                                 # 409
