"""Error classes and error ID constants (PRD §5 / scaffold §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error ID constants (exact strings from scaffold §1.6 / PRD §5) ---------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"                  # 403
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"          # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                            # 404
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"        # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"                    # 409
ERR_START_IN_NO_RIDE_ZONE = "ERR_START_IN_NO_RIDE_ZONE"    # 422
ERR_END_IN_NO_RIDE_ZONE = "ERR_END_IN_NO_RIDE_ZONE"        # 422
ERR_BATTERY_TOO_LOW = "ERR_BATTERY_TOO_LOW"                # 422
ERR_VEHICLE_NOT_AVAILABLE = "ERR_VEHICLE_NOT_AVAILABLE"    # 409
ERR_TECH_WINDOW_OVERLAP = "ERR_TECH_WINDOW_OVERLAP"        # 409
ERR_NO_APPROVED_APPLICATION = "ERR_NO_APPROVED_APPLICATION"  # 422
ERR_INVALID_WINDOW = "ERR_INVALID_WINDOW"                  # 422
ERR_INSUFFICIENT_WALLET = "ERR_INSUFFICIENT_WALLET"        # 422
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                # 400
ERR_STALE_VEHICLE_VERSION = "ERR_STALE_VEHICLE_VERSION"    # 412
ERR_STALE_RIDER_VERSION = "ERR_STALE_RIDER_VERSION"        # 412
ERR_OUTSTANDING_FINES = "ERR_OUTSTANDING_FINES"            # 422


# --- Convenience constructors ----------------------------------------------
def unauthenticated(msg="Missing or malformed authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg="Role is not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_resource_owner(msg="Caller does not own the targeted resource"):
    return ApiError(ERR_NOT_RESOURCE_OWNER, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def reference_not_found(msg="Referenced resource not found"):
    return ApiError(ERR_REFERENCE_NOT_FOUND, 404, msg)


def invalid_state(msg="Operation not allowed from the current state"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def invalid_request(msg="Request body is malformed"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)
