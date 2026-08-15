"""Error classes and error ID constants for the EHS API."""


class ApiError(Exception):
    """Carries an error_id, human-readable message, and HTTP status."""

    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- Error ID constants (from scaffold §1.6 / PRD §5) ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                    # 401
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                    # 400
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"                      # 403
ERR_FORBIDDEN_OWNERSHIP = "ERR_FORBIDDEN_OWNERSHIP"            # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                # 404
ERR_STALE_VERSION = "ERR_STALE_VERSION"                        # 412
ERR_LAB_STATE = "ERR_LAB_STATE"                                # 409
ERR_CONTAINER_STATE = "ERR_CONTAINER_STATE"                    # 409
ERR_PICKUP_STATE = "ERR_PICKUP_STATE"                          # 409
ERR_INSPECTION_STATE = "ERR_INSPECTION_STATE"                  # 409
ERR_CORRECTIVE_ACTION_STATE = "ERR_CORRECTIVE_ACTION_STATE"    # 409
ERR_REGISTRATION_STATE = "ERR_REGISTRATION_STATE"              # 409
ERR_TRAINING_STATE = "ERR_TRAINING_STATE"                      # 409
ERR_INCIDENT_STATE = "ERR_INCIDENT_STATE"                      # 409
ERR_LAB_FROZEN = "ERR_LAB_FROZEN"                              # 409
ERR_CONTROLLED_MATERIAL_UNREGISTERED = "ERR_CONTROLLED_MATERIAL_UNREGISTERED"  # 422
ERR_REQUIRED_TRAINING_INCOMPLETE = "ERR_REQUIRED_TRAINING_INCOMPLETE"          # 422
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"        # 403
ERR_DUPLICATE_BARCODE = "ERR_DUPLICATE_BARCODE"                # 409
ERR_PI_ALREADY_ASSIGNED = "ERR_PI_ALREADY_ASSIGNED"            # 409
ERR_DUPLICATE_ACTIVE_REGISTRATION = "ERR_DUPLICATE_ACTIVE_REGISTRATION"        # 409
ERR_AREA_CAPACITY_EXCEEDED = "ERR_AREA_CAPACITY_EXCEEDED"      # 409
ERR_PICKUP_EMPTY = "ERR_PICKUP_EMPTY"                          # 422
ERR_INVALID_WINDOW = "ERR_INVALID_WINDOW"                      # 400
ERR_INSPECTOR_SCHEDULE_CONFLICT = "ERR_INSPECTOR_SCHEDULE_CONFLICT"            # 409
ERR_DOCK_WINDOW_CONFLICT = "ERR_DOCK_WINDOW_CONFLICT"          # 409
ERR_CROSS_LAB_REFERENCE = "ERR_CROSS_LAB_REFERENCE"            # 422
ERR_DECOMMISSION_BLOCKED = "ERR_DECOMMISSION_BLOCKED"          # 409


def unauthenticated(message="Missing or invalid X-User-ID / X-User-Role headers"):
    return ApiError(ERR_UNAUTHENTICATED, message, 401)


def invalid_request(message="Request body is not well-formed"):
    return ApiError(ERR_INVALID_REQUEST, message, 400)


def forbidden_role(message="Role not permitted for this endpoint"):
    return ApiError(ERR_FORBIDDEN_ROLE, message, 403)


def forbidden_ownership(message="Ownership scope violated"):
    return ApiError(ERR_FORBIDDEN_OWNERSHIP, message, 403)


def not_found(message="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, message, 404)


def stale_version(message="expected_lab_version does not match current lab version"):
    return ApiError(ERR_STALE_VERSION, message, 412)
