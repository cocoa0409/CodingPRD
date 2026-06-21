"""Error classes and error ID constants for the EMS PCB Assembly API."""


class ApiError(Exception):
    """An error carrying an error_id, human message and an HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth / authz
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                       # 403

# Existence
ERR_NOT_FOUND = "ERR_NOT_FOUND"                       # 404
ERR_FK_NOT_FOUND = "ERR_FK_NOT_FOUND"                 # 404

# State
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409

# OCC
ERR_STALE_WORK_ORDER_VERSION = "ERR_STALE_WORK_ORDER_VERSION"  # 412
ERR_STALE_AVL_VERSION = "ERR_STALE_AVL_VERSION"               # 412

# Business / safety
ERR_SOD_VIOLATION = "ERR_SOD_VIOLATION"              # 409
ERR_ROHS_VIOLATION = "ERR_ROHS_VIOLATION"            # 422
ERR_CMRT_MISSING = "ERR_CMRT_MISSING"                # 422
ERR_AVL_NOT_APPROVED = "ERR_AVL_NOT_APPROVED"        # 422
ERR_DESIGNATOR_MISMATCH = "ERR_DESIGNATOR_MISMATCH"  # 422
ERR_NO_APPROVED_SOURCE = "ERR_NO_APPROVED_SOURCE"    # 422
ERR_PROGRAM_NOT_READY = "ERR_PROGRAM_NOT_READY"      # 422
ERR_UNIT_NOT_SHIPPED = "ERR_UNIT_NOT_SHIPPED"        # 422
ERR_KIT_SHORTAGE = "ERR_KIT_SHORTAGE"                # 409
ERR_REWORK_ECO_NOT_APPROVED = "ERR_REWORK_ECO_NOT_APPROVED"  # 422
ERR_OPEN_REWORK_BLOCKS_CLOSE = "ERR_OPEN_REWORK_BLOCKS_CLOSE"  # 409

# Shape / generic
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 400
ERR_VALIDATION = "ERR_VALIDATION"                    # 422


def unauthenticated(msg="Missing or unknown authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Role is not permitted to perform this operation."):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Resource not found."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def fk_not_found(msg="A referenced resource does not exist."):
    return ApiError(ERR_FK_NOT_FOUND, 404, msg)


def invalid_state(msg="Resource is not in a state allowing this transition."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def invalid_request(msg="Request is malformed or missing required fields."):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def validation(msg="A business-rule validation failed."):
    return ApiError(ERR_VALIDATION, 422, msg)
