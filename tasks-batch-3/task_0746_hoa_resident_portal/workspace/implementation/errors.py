"""Error taxonomy for the HOA API — every id/http_status paired here matches PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


ERRORS = {
    "ERR_UNAUTHENTICATED": (401, "X-User-Role header missing or unrecognized"),
    "ERR_UNAUTHORIZED": (403, "Role not permitted for this endpoint"),
    "ERR_NOT_FOUND": (404, "Resource not found"),
    "ERR_FK_NOT_FOUND": (404, "Referenced foreign key not found"),
    "ERR_INVALID_STATE": (409, "Target resource is not in a state that permits the requested transition"),
    "ERR_STALE_VERSION": (412, "expected_homeowner_version does not equal current Homeowner.version"),
    "ERR_PROPERTY_SUSPENDED": (422, "Property is SUSPENDED or homeowner booking privilege is FROZEN"),
    "ERR_REVIEWER_NOT_BOARD": (422, "Reviewer must be a board member"),
    "ERR_AMENITY_WINDOW_VIOLATION": (422, "Reservation window invalid"),
    "ERR_AMENITY_CAPACITY_EXCEEDED": (422, "Amenity capacity exceeded"),
    "ERR_MOTION_WINDOW_CONFLICT": (422, "Motion window overlaps another OPEN motion of the same category"),
    "ERR_BALLOT_DUPLICATE": (409, "Homeowner has already cast a ballot on this motion"),
    "ERR_APPEAL_NON_APPEALABLE": (422, "SAFETY violations are non-appealable"),
    "ERR_APPEAL_WINDOW_EXPIRED": (422, "Appeal window has expired"),
    "ERR_OVERPAYMENT": (422, "Payment amount exceeds outstanding balance"),
    "ERR_HOMEOWNER_DELINQUENT": (422, "Homeowner is DELINQUENT"),
    "ERR_REVISION_LIMIT": (422, "ARCRequest revision_count has reached 3"),
    "ERR_INVALID_REQUEST": (400, "Payload malformed, required field missing, or field invalid"),
    "ERR_UNIQUE_VIOLATION": (409, "Uniqueness constraint violated"),
}


def raise_error(error_id, message=None):
    http, default_msg = ERRORS[error_id]
    raise ApiError(error_id, http, message or default_msg)
