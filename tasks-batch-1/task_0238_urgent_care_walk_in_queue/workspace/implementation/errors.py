"""Error classes and the error catalog (§1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status by error_id (PRD §5 catalogue).
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_QUEUE_ORDER_VIOLATION": 409,
    "ERR_ISOLATION_REQUIRED": 409,
    "ERR_CLINIC_ON_DIVERSION": 409,
    "ERR_ROOM_UNAVAILABLE": 409,
    "ERR_PROVIDER_AT_CAPACITY": 409,
    "ERR_SLOT_CONFLICT": 409,
    "ERR_ROOM_SLOT_CONFLICT": 409,
    "ERR_OCC_ROOM_REQUIRED": 422,
    "ERR_REGISTRATION_INCOMPLETE": 409,
    "ERR_GUARANTOR_REQUIRED": 422,
    "ERR_AMBULANCE_REQUIRED": 409,
    "ERR_CHARGES_NOT_FINALIZED": 409,
    "ERR_BILLING_FROZEN": 409,
    "ERR_COVERAGE_TYPE_MISMATCH": 422,
    "ERR_VALIDATION_PAGINATION": 400,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP[error_id], message)
