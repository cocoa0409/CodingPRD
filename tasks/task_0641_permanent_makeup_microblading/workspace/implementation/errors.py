"""Error catalogue. Each error_id maps to an HTTP status per PRD section 5."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


# PRD section 5 error code catalogue
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_AGE_NOT_VERIFIED = ("ERR_AGE_NOT_VERIFIED", 422)
ERR_CONSENT_MISSING = ("ERR_CONSENT_MISSING", 422)
ERR_PATCH_TEST_FAILED = ("ERR_PATCH_TEST_FAILED", 422)
ERR_COOLING_OFF_VIOLATION = ("ERR_COOLING_OFF_VIOLATION", 422)
ERR_MEDICAL_CLEARANCE_REQUIRED = ("ERR_MEDICAL_CLEARANCE_REQUIRED", 422)
ERR_CLIENT_BLOCKED = ("ERR_CLIENT_BLOCKED", 422)
ERR_LICENSE_INVALID = ("ERR_LICENSE_INVALID", 422)
ERR_NO_STERILE_KIT = ("ERR_NO_STERILE_KIT", 422)
ERR_TOUCHUP_WINDOW_CLOSED = ("ERR_TOUCHUP_WINDOW_CLOSED", 422)
ERR_REFRESH_NOT_DUE = ("ERR_REFRESH_NOT_DUE", 422)
ERR_REDO_NOT_ELIGIBLE = ("ERR_REDO_NOT_ELIGIBLE", 422)
ERR_DEPOSIT_AMOUNT_MISMATCH = ("ERR_DEPOSIT_AMOUNT_MISMATCH", 422)
ERR_VALIDATION_RANGE = ("ERR_VALIDATION_RANGE", 422)


def err(code_tuple, message=None):
    error_id, http_status = code_tuple
    return ApiError(error_id, http_status, message)
