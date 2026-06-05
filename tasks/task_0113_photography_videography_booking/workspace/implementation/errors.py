"""Domain error classes and error_id constants.

Error IDs and HTTP statuses are taken verbatim from the PRD §5 error catalogue
and SCAFFOLD §1.6.
"""
from __future__ import annotations


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---- Error ID constants (PRD §5 / SCAFFOLD §1.6) ----------------------------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"             # 403
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"     # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                       # 404
ERR_INVALID_REFERENCE = "ERR_INVALID_REFERENCE"       # 422
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_STALE_BOOKING_VERSION = "ERR_STALE_BOOKING_VERSION"     # 412
ERR_STALE_SCHEDULE_VERSION = "ERR_STALE_SCHEDULE_VERSION"   # 412
ERR_MODEL_RELEASE_REQUIRED = "ERR_MODEL_RELEASE_REQUIRED"   # 422
ERR_CONTRACT_NOT_SIGNED = "ERR_CONTRACT_NOT_SIGNED"   # 422
ERR_SCHEDULE_CONFLICT = "ERR_SCHEDULE_CONFLICT"       # 409
ERR_SHOOTER_DOUBLE_BOOKED = "ERR_SHOOTER_DOUBLE_BOOKED"     # 409
ERR_LEAD_PHOTOGRAPHER_BUSY = "ERR_LEAD_PHOTOGRAPHER_BUSY"   # 409
ERR_RESCHEDULE_LIMIT = "ERR_RESCHEDULE_LIMIT"         # 409
ERR_REVISION_LIMIT = "ERR_REVISION_LIMIT"             # 409
ERR_INSUFFICIENT_IMAGES = "ERR_INSUFFICIENT_IMAGES"   # 422
ERR_PAYMENT_AMOUNT_MISMATCH = "ERR_PAYMENT_AMOUNT_MISMATCH"  # 422
ERR_SHOOT_NOT_ENDED = "ERR_SHOOT_NOT_ENDED"           # 409
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"           # 422
ERR_DUPLICATE_RESOURCE = "ERR_DUPLICATE_RESOURCE"     # 409
ERR_PACKAGE_INACTIVE = "ERR_PACKAGE_INACTIVE"         # 422
