"""Domain error class and error_id constants (scaffold §1.6 / PRD §5)."""
from __future__ import annotations


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id constants — verbatim from scaffold §1.6 / PRD §5
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_INSURANCE_INVALID = "ERR_INSURANCE_INVALID"
ERR_LIVEABOARD_NOT_ALLOWED = "ERR_LIVEABOARD_NOT_ALLOWED"
ERR_SLIP_SIZE_MISMATCH = "ERR_SLIP_SIZE_MISMATCH"
ERR_SLIP_DATE_CONFLICT = "ERR_SLIP_DATE_CONFLICT"
ERR_INVALID_DATE_RANGE = "ERR_INVALID_DATE_RANGE"
ERR_LIVEABOARD_QUOTA_EXCEEDED = "ERR_LIVEABOARD_QUOTA_EXCEEDED"
ERR_VESSEL_TENANT_MISMATCH = "ERR_VESSEL_TENANT_MISMATCH"
ERR_WAITLIST_INELIGIBLE = "ERR_WAITLIST_INELIGIBLE"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
