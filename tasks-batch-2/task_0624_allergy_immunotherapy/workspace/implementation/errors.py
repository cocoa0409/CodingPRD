"""Error catalog (PRD Section 5 / scaffold 1.6).

Each error carries an error_id (machine-readable), an HTTP status, and a
human-readable message. The error_id and http_status values are taken verbatim
from the scaffold error catalog.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status per error_id (PRD Section 5 / scaffold 1.6 errors table).
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 404,
    "ERR_STALE_PLAN_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_PANEL_NOT_OPEN": 409,
    "ERR_PANEL_EMPTY": 422,
    "ERR_NO_POSITIVE_TEST": 422,
    "ERR_PANEL_NOT_FINALIZED": 409,
    "ERR_PLAN_NOT_DRAFT": 409,
    "ERR_PLAN_NOT_ACTIVE": 409,
    "ERR_PLAN_HELD": 409,
    "ERR_PLAN_NOT_HELD": 409,
    "ERR_NOT_AT_MAINTENANCE": 409,
    "ERR_OPEN_VISIT_EXISTS": 409,
    "ERR_PLAN_NOT_DISCONTINUABLE": 409,
    "ERR_NO_STARTING_VIAL": 422,
    "ERR_PATIENT_INACTIVE": 422,
    "ERR_LOT_NOT_AVAILABLE": 409,
    "ERR_DUPLICATE_LOT_NUMBER": 409,
    "ERR_VIAL_NOT_USABLE": 422,
    "ERR_VIAL_INSUFFICIENT_VOLUME": 422,
    "ERR_VIAL_PLAN_MISMATCH": 422,
    "ERR_EPINEPHRINE_NOT_ON_FILE": 422,
    "ERR_EPINEPHRINE_REQUIRED": 422,
    "ERR_TEST_METHOD_MISMATCH": 422,
    "ERR_OBSERVATION_NOT_ELAPSED": 422,
    "ERR_REACTION_GRADE_MISMATCH": 422,
    "ERR_VISIT_NOT_ADMINISTERED": 409,
    "ERR_INVALID_REQUEST": 400,
}


def err(error_id, message=None):
    """Build an ApiError using the catalog's HTTP status for error_id."""
    return ApiError(error_id, ERROR_STATUS[error_id], message)
