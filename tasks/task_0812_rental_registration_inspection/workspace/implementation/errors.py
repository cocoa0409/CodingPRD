"""Error catalog and the ApiError exception type."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status for each error id (from the scaffold error catalog).
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN_OWNERSHIP": 403,
    "ERR_VALIDATION": 422,
    "ERR_LANDLORD_NOT_FOUND": 404,
    "ERR_PROPERTY_NOT_FOUND": 404,
    "ERR_LICENSE_NOT_FOUND": 404,
    "ERR_INSPECTOR_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_VIOLATION_NOT_FOUND": 404,
    "ERR_COMPLAINT_NOT_FOUND": 404,
    "ERR_NOTICE_NOT_FOUND": 404,
    "ERR_CONDEMNATION_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_PROPERTY_NOT_REGISTERED": 409,
    "ERR_NO_PASSED_INSPECTION": 409,
    "ERR_UNSAFE_HABITABILITY": 409,
    "ERR_ESCALATION_THRESHOLD_NOT_MET": 409,
    "ERR_NO_CONDEMNATION_BASIS": 409,
    "ERR_INSPECTOR_DOUBLE_BOOKED": 409,
    "ERR_INSPECTION_COOLDOWN": 409,
    "ERR_REINSPECTION_TOO_EARLY": 422,
    "ERR_NOTICE_EXPIRED": 409,
    "ERR_FEE_MISMATCH": 402,
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS.get(error_id, 400), message)
