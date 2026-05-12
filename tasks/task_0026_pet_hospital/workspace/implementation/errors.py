"""Domain error classes & catalog."""
from __future__ import annotations


class ApiError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Catalog: error_id → http_status
ERROR_HTTP = {
    "ERR_AUTH_MISSING": 401,
    "ERR_AUTH_INVALID_ROLE": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 409,
    "ERR_PET_ARCHIVED": 409,
    "ERR_OWNER_NOT_VERIFIED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_DOSAGE_OUT_OF_RANGE": 422,
    "ERR_SEVERE_INTERACTION": 422,
    "ERR_PENDING_PRESCRIPTIONS": 409,
    "ERR_LAB_ITEMS_INVALID": 422,
    "ERR_CAGE_CAPACITY_EXCEEDED": 409,
    "ERR_CAGE_OVERLAP_CAPACITY": 409,
    "ERR_INSUFFICIENT_DEPOSIT": 402,
    "ERR_VACCINE_AGE_MIN": 422,
    "ERR_VACCINE_COOLDOWN": 422,
    "ERR_BATCH_RECALLED": 422,
    "ERR_REFUND_EXCEEDS_PAID": 422,
    "ERR_DUPLICATE_EVENT": 409,
    "ERR_PRESCRIPTION_ALREADY_REVIEWED": 409,
    "ERR_NO_VET_AVAILABLE": 409,
    "ERR_VALIDATION_FAILED": 422,
}


def err(error_id: str, message: str = "") -> ApiError:
    return ApiError(error_id, message or error_id, ERROR_HTTP[error_id])
