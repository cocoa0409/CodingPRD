"""Domain error class + error_id/http_status catalogue (PRD §5)."""
from __future__ import annotations


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error id -> HTTP status, verbatim from PRD §5 / scaffold §1.6.
ERROR_STATUS = {
    "ERR_MISSING_AUTH": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCED_ENTITY_NOT_FOUND": 422,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_ADMISSIONS_FROZEN": 403,
    "ERR_RESIDENCY_NOT_DEPOSIT_HELD": 409,
    "ERR_RESIDENCY_NOT_RESERVED": 409,
    "ERR_RESIDENCY_NOT_ACTIVE": 409,
    "ERR_RESIDENCY_NOT_WAITLISTED": 409,
    "ERR_NO_UNIT_ASSIGNED": 409,
    "ERR_UNIT_NOT_AVAILABLE": 409,
    "ERR_UNIT_CARE_LEVEL_MISMATCH": 422,
    "ERR_DUPLICATE_WAITLIST_ENTRY": 409,
    "ERR_WAITLIST_ENTRY_NOT_PENDING": 409,
    "ERR_WAITLIST_ENTRY_NOT_PLACEABLE": 409,
    "ERR_WAITLIST_ENTRY_NOT_WITHDRAWABLE": 409,
    "ERR_WAITLIST_NOT_HEAD": 409,
    "ERR_CARE_TRANSITION_NOT_PROPOSED": 409,
    "ERR_INVALID_CARE_STEP": 422,
    "ERR_NO_BED_OCCUPIED": 409,
    "ERR_SECOND_PERSON_EXISTS": 409,
    "ERR_BED_RESERVATION_NOT_HELD": 409,
    "ERR_BED_RESERVATION_NOT_RELEASABLE": 409,
    "ERR_BED_RESERVATION_EXPIRED": 409,
    "ERR_INVALID_HOLD_WINDOW": 422,
    "ERR_BED_CAPACITY_EXCEEDED": 409,
    "ERR_UNIT_NOT_SKILLED": 422,
    "ERR_INVALID_CLOCK_ADVANCE": 422,
    "ERR_RESOLUTION_NOT_DRAFT": 409,
    "ERR_RESOLUTION_NOT_OPEN": 409,
    "ERR_DUPLICATE_VOTE": 409,
    "ERR_QUORUM_NOT_MET": 409,
}


def err(error_id: str, message: str = ""):
    """Raise an APIError, resolving the HTTP status from the catalogue."""
    raise APIError(error_id, ERROR_STATUS[error_id], message or error_id)
