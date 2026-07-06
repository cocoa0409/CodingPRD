"""Error catalog and ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http_status
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_FK_MISMATCH": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_SCAN_VERSION": 412,
    "ERR_STALE_SUBSCRIPTION_VERSION": 412,
    "ERR_SITE_BLOCKED_BY_LEGAL": 409,
    "ERR_SCAN_NOT_COMPLETED": 409,
    "ERR_VPAT_NOT_ISSUED": 409,
    "ERR_SUBSCRIPTION_NOT_ACTIVE": 409,
    "ERR_EMPTY_FINDINGS": 422,
    "ERR_SCORE_BELOW_PASS": 422,
    "ERR_DUPLICATE_SITE_URL": 409,
    "ERR_SUBSCRIPTION_EXISTS": 409,
    "ERR_NOT_YET_EXPIRED": 409,
    "ERR_INVALID_FIELD_VALUE": 422,
    "ERR_MISSING_REQUIRED_FIELD": 422,
    "ERR_INVALID_PAGINATION": 422,
    "ERR_INVALID_DATETIME": 422,
    "ERR_SUPERSEDE_TARGET_NOT_REJECTED": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
