"""Error catalogue (PRD Section 5 / SCAFFOLD §1.6).

Each ApiError carries an error_id, a human-readable message, and an HTTP status.
The error response body uses the exact field names from the response envelope:
data.error_id and data.message.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status for each error_id (PRD Section 5 Error Code Catalogue).
ERROR_HTTP = {
    # auth
    "ERR_MISSING_AUTH": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_OWNERSHIP_MISMATCH": 403,
    # not found
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_INTAKE_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_PACKAGE_NOT_FOUND": 404,
    "ERR_APPT_NOT_FOUND": 404,
    "ERR_DISPENSE_NOT_FOUND": 404,
    "ERR_PRACTITIONER_NOT_FOUND": 404,
    "ERR_ROOM_NOT_FOUND": 404,
    "ERR_FORMULA_NOT_FOUND": 404,
    "ERR_HERB_NOT_FOUND": 404,
    # request validation
    "ERR_INVALID_REQUEST": 400,
    # state
    "ERR_APPT_NOT_SCHEDULED": 409,
    "ERR_APPT_NOT_CHECKED_IN": 409,
    "ERR_APPT_NOT_CANCELLABLE": 409,
    "ERR_PLAN_NOT_ACTIVE": 409,
    "ERR_PLAN_NOT_ON_HOLD": 409,
    "ERR_PLAN_NOT_CANCELLABLE": 409,
    "ERR_PLAN_HAS_OPEN_APPOINTMENTS": 409,
    "ERR_INTAKE_NOT_DRAFT": 409,
    "ERR_INTAKE_INCOMPLETE": 409,
    "ERR_DISPENSE_NOT_REQUESTED": 409,
    "ERR_DISPENSE_NOT_FILLED": 409,
    # business referential / cross-entity
    "ERR_INTAKE_REQUIRED": 409,
    "ERR_INTAKE_NOT_FINALIZED": 409,
    # business safety / temporal / fiscal
    "ERR_INSUFFICIENT_STOCK": 409,
    "ERR_ROOM_CONFLICT": 409,
    "ERR_PRACTITIONER_CONFLICT": 409,
    "ERR_NO_CREDITS_REMAINING": 409,
    "ERR_PACKAGE_HAS_CONSUMED_CREDITS": 409,
    "ERR_PACKAGE_HAS_RESERVED_CREDITS": 409,
    # concurrency
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP[error_id], message)
