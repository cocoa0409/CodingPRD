"""Error catalog (SCAFFOLD §1.6 / PRD §5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http status
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_VALIDATION": 400,
    "ERR_COLOR_SYSTEM_MISMATCH": 422,
    "ERR_SELF_REFERRAL": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_SALES_NOT_ACCEPTED": 409,
    "ERR_ASSESSMENT_NOT_APPROVED": 409,
    "ERR_CREW_NOT_METALLIC_CERTIFIED": 422,
    "ERR_CREW_DAY_DOUBLE_BOOKED": 409,
    "ERR_SITE_CURE_WINDOW_OVERLAP": 409,
    "ERR_CREW_CAPACITY_EXCEEDED": 422,
    "ERR_CURE_WINDOW_NOT_ELAPSED": 409,
    "ERR_INSTALL_DATE_NOT_REACHED": 409,
    "ERR_COVERAGE_EXPIRED": 409,
    "ERR_DEFECT_NOT_COVERED": 422,
    "ERR_FINANCING_PRINCIPAL_TOO_LOW": 422,
    "ERR_STALE_PROJECT_VERSION": 412,
    "ERR_PROJECT_NOT_CANCELLABLE": 409,
    "ERR_DECLINE_AFTER_SCHEDULED": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
