"""Error classes and error-id constants (from PRD §5 / SCAFFOLD §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth / authz
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                        # 403
# Existence
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
# Request well-formedness
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"            # 422
ERR_VALIDATION_OUT_OF_RANGE = "ERR_VALIDATION_OUT_OF_RANGE"  # 422
# OCC
ERR_STALE_VERSION = "ERR_STALE_VERSION"               # 412
# State
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
# Business rules
ERR_DISCLOSURE_REQUIRED = "ERR_DISCLOSURE_REQUIRED"   # 409
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 409
ERR_DEATH_CERT_REQUIRED = "ERR_DEATH_CERT_REQUIRED"   # 409
ERR_INTERMENT_NOT_READY = "ERR_INTERMENT_NOT_READY"   # 409
ERR_INTERMENT_INCOMPLETE = "ERR_INTERMENT_INCOMPLETE"  # 409
ERR_CONTRACT_NOT_FUNDED = "ERR_CONTRACT_NOT_FUNDED"   # 409
ERR_CONTRACT_REQUIRED = "ERR_CONTRACT_REQUIRED"       # 409
ERR_GFS_NOT_ISSUED = "ERR_GFS_NOT_ISSUED"             # 409
ERR_EMPTY_STATEMENT = "ERR_EMPTY_STATEMENT"           # 409
ERR_FUNDING_SHORTFALL = "ERR_FUNDING_SHORTFALL"       # 409
ERR_TRUST_UNDERFUNDED = "ERR_TRUST_UNDERFUNDED"       # 409
ERR_SCHEDULE_CONFLICT = "ERR_SCHEDULE_CONFLICT"       # 409
ERR_PLOT_NOT_AVAILABLE = "ERR_PLOT_NOT_AVAILABLE"     # 409
ERR_PLOT_NOT_RESERVED = "ERR_PLOT_NOT_RESERVED"       # 409
ERR_NON_DECLINABLE_LINE = "ERR_NON_DECLINABLE_LINE"   # 409
ERR_NOT_AMENDABLE = "ERR_NOT_AMENDABLE"               # 409
ERR_FUNDING_TYPE_MISMATCH = "ERR_FUNDING_TYPE_MISMATCH"  # 409
ERR_PERMIT_NOT_APPLIED = "ERR_PERMIT_NOT_APPLIED"     # 409
ERR_PERMIT_NOT_REJECTED = "ERR_PERMIT_NOT_REJECTED"   # 409
ERR_CONTRACT_EXISTS = "ERR_CONTRACT_EXISTS"           # 409


def unauthenticated(msg="Missing or unknown authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Acting role is not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Request body is malformed"):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def out_of_range(msg="Pagination parameter outside allowed bounds"):
    return ApiError(ERR_VALIDATION_OUT_OF_RANGE, 422, msg)


def stale_version(msg="Optimistic concurrency version mismatch"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def invalid_state(msg="Resource is not in a state from which this transition is defined"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def conflict(error_id, msg=None):
    return ApiError(error_id, 409, msg or error_id)
