"""Error classes and error IDs from the scaffold error catalog."""


class ApiError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error ID constants (SCAFFOLD errors table)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                    # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                                # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                # 404
ERR_VALIDATION = "ERR_VALIDATION"                              # 400
ERR_STALE_VERSION = "ERR_STALE_VERSION"                        # 412
ERR_INVALID_STATE = "ERR_INVALID_STATE"                        # 409
ERR_FACILITY_INACTIVE = "ERR_FACILITY_INACTIVE"                # 409
ERR_PRODUCT_UNAVAILABLE = "ERR_PRODUCT_UNAVAILABLE"            # 409
ERR_INSUFFICIENT_STOCK = "ERR_INSUFFICIENT_STOCK"              # 409
ERR_TRAINING_NOT_CERTIFIED = "ERR_TRAINING_NOT_CERTIFIED"      # 409
ERR_INCOMPATIBLE_PLACEMENT = "ERR_INCOMPATIBLE_PLACEMENT"      # 409
ERR_TECHNICIAN_WINDOW_CONFLICT = "ERR_TECHNICIAN_WINDOW_CONFLICT"  # 409
ERR_PROTECTION_WINDOW_OVERLAP = "ERR_PROTECTION_WINDOW_OVERLAP"    # 409
ERR_CLOCK_REGRESSION = "ERR_CLOCK_REGRESSION"                  # 400
ERR_DUPLICATE_STANDING_ORDER = "ERR_DUPLICATE_STANDING_ORDER"  # 409
ERR_TRIAL_ALREADY_ACTIVE = "ERR_TRIAL_ALREADY_ACTIVE"          # 409
ERR_DISCONTINUE_BLOCKED = "ERR_DISCONTINUE_BLOCKED"            # 409
ERR_ARCHIVE_BLOCKED = "ERR_ARCHIVE_BLOCKED"                    # 409
ERR_CREDIT_LIMIT_EXCEEDED = "ERR_CREDIT_LIMIT_EXCEEDED"        # 409


def unauthenticated(msg="Missing or invalid authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, msg, 401)


def forbidden(msg="Role not permitted for this endpoint"):
    return ApiError(ERR_FORBIDDEN, msg, 403)


def not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def validation(msg="Invalid request"):
    return ApiError(ERR_VALIDATION, msg, 400)


def stale_version(msg="Expected version does not match current version"):
    return ApiError(ERR_STALE_VERSION, msg, 412)


def invalid_state(msg="State transition not allowed from current state"):
    return ApiError(ERR_INVALID_STATE, msg, 409)


def facility_inactive(msg="Facility is not ACTIVE"):
    return ApiError(ERR_FACILITY_INACTIVE, msg, 409)
