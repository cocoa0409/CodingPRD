"""Error classes and error ID constants for the Earned Wage Access API.

Every error_id and its HTTP status comes directly from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth / authz
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"           # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                 # 403
# Existence / referential
ERR_NOT_FOUND = "ERR_NOT_FOUND"                       # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"           # 400
ERR_CROSS_EMPLOYER_REFERENCE = "ERR_CROSS_EMPLOYER_REFERENCE"  # 422
# State / OCC / SoD
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"               # 412
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 403
# Business
ERR_EMPLOYER_FROZEN = "ERR_EMPLOYER_FROZEN"           # 409
ERR_WORKER_NOT_ACTIVE = "ERR_WORKER_NOT_ACTIVE"       # 409
ERR_WORKER_ON_HOLD = "ERR_WORKER_ON_HOLD"             # 409
ERR_COOLING_OFF_ACTIVE = "ERR_COOLING_OFF_ACTIVE"     # 409
ERR_PERIOD_CAP_REACHED = "ERR_PERIOD_CAP_REACHED"     # 409
ERR_TIME_ENTRY_OUT_OF_WINDOW = "ERR_TIME_ENTRY_OUT_OF_WINDOW"  # 422
ERR_SHIFT_OVERLAP = "ERR_SHIFT_OVERLAP"               # 409
ERR_PERIOD_OVERLAP = "ERR_PERIOD_OVERLAP"             # 409
ERR_BELOW_FLOOR = "ERR_BELOW_FLOOR"                   # 422
ERR_OVER_RECOUP = "ERR_OVER_RECOUP"                   # 422
ERR_INSUFFICIENT_FUNDING = "ERR_INSUFFICIENT_FUNDING"  # 402
ERR_DUPLICATE_PAYROLL_REF = "ERR_DUPLICATE_PAYROLL_REF"  # 409
ERR_BATCH_ALREADY_POSTED = "ERR_BATCH_ALREADY_POSTED"  # 409
ERR_NO_POSTED_BATCH = "ERR_NO_POSTED_BATCH"           # 409
ERR_PERIOD_NOT_LOCKED = "ERR_PERIOD_NOT_LOCKED"       # 409
ERR_PERIOD_HAS_POSTED_BATCH = "ERR_PERIOD_HAS_POSTED_BATCH"  # 409
ERR_PERIOD_NOT_DISBURSED = "ERR_PERIOD_NOT_DISBURSED"  # 409
ERR_NOTHING_TO_WRITE_OFF = "ERR_NOTHING_TO_WRITE_OFF"  # 409
ERR_WORKER_HAS_OPEN_ADVANCE = "ERR_WORKER_HAS_OPEN_ADVANCE"  # 409
ERR_STATEMENT_NOT_CLEAN = "ERR_STATEMENT_NOT_CLEAN"   # 409


def unauthenticated(msg="Missing or unknown authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="Role not permitted for this operation"):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid request body"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def cross_employer(msg="Body foreign key belongs to a different employer"):
    return ApiError(ERR_CROSS_EMPLOYER_REFERENCE, 422, msg)


def invalid_state(msg="Transition not defined from the current state"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_version(msg="Stale version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def segregation_of_duties(msg="Segregation of duties violated"):
    return ApiError(ERR_SEGREGATION_OF_DUTIES, 403, msg)
