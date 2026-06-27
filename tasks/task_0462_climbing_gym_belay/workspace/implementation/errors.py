"""Error catalog and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP statuses keyed by error id (from PRD §5 / scaffold §1.6)
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_WAIVER_INVALID": 422,
    "ERR_BELAY_CERT_REQUIRED": 422,
    "ERR_BELAY_PREREQUISITE_MISSING": 422,
    "ERR_MEMBERSHIP_NOT_ACTIVE": 422,
    "ERR_MEMBERSHIP_FROZEN": 409,
    "ERR_ENROLLMENT_WINDOW_CLOSED": 422,
    "ERR_CAPACITY_FULL": 422,
    "ERR_STALE_FACILITY_VERSION": 412,
    "ERR_STALE_CLINIC_VERSION": 412,
    "ERR_STALE_MEMBERSHIP_VERSION": 412,
    "ERR_STALE_RENTAL_VERSION": 412,
    "ERR_STALE_ROUTE_VERSION": 412,
    "ERR_DUPLICATE_EMAIL": 409,
    "ERR_DUPLICATE_WAIVER": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
