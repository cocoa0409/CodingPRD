"""Error catalog and the ApiError exception type."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error ID -> HTTP status (from PRD §5 / scaffold §1.6)
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_PATIENT_VERSION": 412,
    "ERR_PATIENT_DISMISSED": 409,
    "ERR_PAYER_MODE_MISMATCH": 422,
    "ERR_RESOURCE_UNAVAILABLE": 409,
    "ERR_ROOM_TYPE_MISMATCH": 422,
    "ERR_PROVIDER_DOUBLE_BOOKED": 409,
    "ERR_ROOM_BUFFER_CONFLICT": 409,
    "ERR_POLICY_REQUIRED": 422,
    "ERR_VISIT_CAP_EXCEEDED": 409,
    "ERR_SOAP_NOTE_REQUIRED": 409,
    "ERR_ACTIVE_PLAN_EXISTS": 409,
    "ERR_PLAN_NOT_READY": 409,
    "ERR_SOAP_PROVIDER_MISMATCH": 422,
    "ERR_REGRESSION_NOT_ALLOWED": 409,
    "ERR_VALIDATION": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
