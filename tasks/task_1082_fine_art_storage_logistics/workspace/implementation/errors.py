"""Error definitions for the Fine-Art Storage & Logistics API."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> HTTP status
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_OWNERSHIP_REQUIRED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 400,
    "ERR_TIME_WINDOW_INVALID": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_ARTWORK_CONDITION_UNSAFE": 422,
    "ERR_ARTWORK_NOT_AVAILABLE": 409,
    "ERR_CRATE_NOT_READY": 409,
    "ERR_CLIMATE_MISMATCH": 422,
    "ERR_NO_FINALIZED_APPRAISAL": 422,
    "ERR_POLICY_NOT_ACTIVE": 409,
    "ERR_POLICY_EXPIRED": 409,
    "ERR_CARNET_REQUIRED": 422,
    "ERR_CARNET_EXPIRED": 409,
    "ERR_CREW_UNAVAILABLE": 409,
    "ERR_ROOM_UNAVAILABLE": 409,
    "ERR_ROOM_NOT_OPERATIONAL": 409,
    "ERR_VAULT_UNAVAILABLE": 409,
    "ERR_VAULT_FULL": 409,
    "ERR_INSUFFICIENT_COVERAGE": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
