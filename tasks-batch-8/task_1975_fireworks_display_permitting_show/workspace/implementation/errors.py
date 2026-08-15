"""Error catalog: error_id -> HTTP status, plus the ApiError exception."""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_FORBIDDEN_OWNERSHIP": 403,
    "ERR_SOD_VIOLATION": 403,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_QUANTITY": 400,
    "ERR_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_OPERATOR_SUSPENDED": 409,
    "ERR_MAGAZINE_LAPSED": 409,
    "ERR_PERMIT_NOT_APPROVED": 409,
    "ERR_DUPLICATE_APPLICATION": 409,
    "ERR_BATCH_QUARANTINED": 409,
    "ERR_LICENSE_EXPIRED": 409,
    "ERR_CERT_NOT_VALID": 409,
    "ERR_WEATHER_STALE": 409,
    "ERR_SOAK_INCOMPLETE": 409,
    "ERR_SHOW_WINDOW_NOT_OPEN": 409,
    "ERR_VENUE_CONFLICT": 409,
    "ERR_INSUFFICIENT_PRODUCT": 409,
    "ERR_SECURITY_NOT_SECURED": 409,
    "ERR_NO_PRODUCT_ON_SITE": 409,
    "ERR_FALLOUT_EXCEEDS_BOUNDARY": 422,
    "ERR_WEATHER_NO_GO": 422,
    "ERR_SCOPE_MISMATCH": 422,
    "ERR_MAGAZINE_CAPACITY_EXCEEDED": 422,
    "ERR_SWEEP_RECONCILE_FAILED": 422,
    "ERR_MANIFEST_NOT_COMPLIANT": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=""):
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or error_id
        super().__init__(self.message)


def err(error_id, message=""):
    raise ApiError(error_id, message)
