"""Error catalog (PRD section 5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


# error_id -> HTTP status.  Every code from PRD section 5.
ERROR_HTTP = {
    # Authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # Request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    # Existence
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_DEPARTURE_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_PILGRIM_NOT_FOUND": 404,
    "ERR_PAYMENT_PLAN_NOT_FOUND": 404,
    "ERR_PAYMENT_NOT_FOUND": 404,
    "ERR_AIR_BLOCK_NOT_FOUND": 404,
    "ERR_SACRED_SITE_NOT_FOUND": 404,
    "ERR_SERVICE_BOOKING_NOT_FOUND": 404,
    "ERR_LAND_RESOURCE_NOT_FOUND": 404,
    "ERR_LAND_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_PROTECTION_NOT_FOUND": 404,
    "ERR_ADVISORY_NOT_FOUND": 404,
    # State
    "ERR_DEPARTURE_INVALID_STATE": 409,
    "ERR_PILGRIM_NOT_ACTIVE": 409,
    "ERR_AGREEMENT_INVALID_STATE": 409,
    "ERR_PLAN_INVALID_STATE": 409,
    "ERR_PAYMENT_ALREADY_REVERSED": 409,
    "ERR_AIR_BLOCK_INVALID_STATE": 409,
    "ERR_SERVICE_BOOKING_INVALID_STATE": 409,
    "ERR_LAND_ASSIGNMENT_INVALID_STATE": 409,
    "ERR_PROTECTION_INVALID_STATE": 409,
    "ERR_ADVISORY_INVALID_STATE": 409,
    "ERR_NO_PENDING_MODIFICATION": 409,
    # Optimistic concurrency
    "ERR_STALE_PILGRIM_VERSION": 412,
    "ERR_STALE_DEPARTURE_VERSION": 412,
    # Business safety
    "ERR_MOBILITY_UNSUPPORTED": 422,
    "ERR_MOBILITY_ACCOMMODATION_UNMET": 422,
    "ERR_DEPARTURE_SUSPENDED_NO_NEW_BOOKINGS": 422,
    "ERR_RISK_ACKNOWLEDGEMENT_REQUIRED": 422,
    "ERR_DEPARTURE_POSTURE_BLOCKS_CONFIRM": 422,
    "ERR_SENIOR_PROTECTION_REQUIRED": 422,
    # Temporal
    "ERR_NAME_CHANGE_DEADLINE_PASSED": 422,
    "ERR_DIETARY_LEAD_TIME_UNMET": 422,
    "ERR_WAIVER_WINDOW_CLOSED": 422,
    "ERR_ADVISORY_EFFECTIVE_IN_FUTURE": 422,
    # Capacity / constraint
    "ERR_AIR_BLOCK_SEATS_EXHAUSTED": 409,
    "ERR_SITE_SLOT_CONFLICT": 409,
    "ERR_SITE_DAILY_CAPACITY_EXCEEDED": 409,
    "ERR_LAND_RESOURCE_OVERSUBSCRIBED": 409,
    "ERR_ROOM_CAPACITY_EXCEEDED": 409,
    "ERR_NO_APPLICABLE_PRICE_TIER": 422,
    "ERR_MIN_PAX_NOT_MET": 422,
    "ERR_PENDING_MODIFICATION_UNRATIFIED": 422,
    # Referential / consistency
    "ERR_AGREEMENT_DEPARTURE_MISMATCH": 422,
    "ERR_ROOMMATE_INVALID": 422,
    "ERR_AIR_BLOCK_NOT_CONFIRMED": 422,
    "ERR_CLERGY_NOT_CONFIRMED": 422,
    "ERR_PERMIT_REFERENCE_REQUIRED": 422,
    "ERR_WAIVER_NOT_ELIGIBLE": 422,
    "ERR_NO_EARNED_FREE_SEAT": 422,
    # Fiscal
    "ERR_OVERPAYMENT_NOT_ALLOWED": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication required.",
    "ERR_UNAUTHORIZED": "Role is not permitted to perform this operation.",
    "ERR_SEGREGATION_OF_DUTIES": "The same user may not perform both halves of this control.",
    "ERR_INVALID_REQUEST": "Request payload is invalid.",
    "ERR_INVALID_PAGINATION": "Pagination parameters are invalid.",
}


def err(error_id, message=None):
    raise ApiError(error_id, ERROR_HTTP[error_id], message)
