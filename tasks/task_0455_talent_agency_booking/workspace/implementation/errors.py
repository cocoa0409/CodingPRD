"""Error classes and the error catalog (id -> HTTP status)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else ERROR_STATUS.get(error_id, 400)
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


# Error catalog from PRD §5 / scaffold §1.6
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_DATE_RANGE": 422,
    "ERR_STALE_TALENT_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_CROSS_ENTITY_GATE": 409,
    "ERR_DEAL_NOT_ACCEPTED": 409,
    "ERR_SUBMISSION_NOT_OFFERABLE": 409,
    "ERR_AUDITION_NOT_COMPLETED": 409,
    "ERR_BOOKING_NOT_COMPLETED": 409,
    "ERR_CASTING_CALL_NOT_OPEN": 409,
    "ERR_TALENT_NOT_ROSTERED": 409,
    "ERR_HOLD_NOT_ACTIVE": 409,
    "ERR_TALENT_MISMATCH": 409,
    "ERR_SLOT_NOT_ENDED": 409,
    "ERR_BOOKING_NOT_ENDED": 409,
    "ERR_BOOKING_ALREADY_PAID": 409,
    "ERR_TALENT_HAS_OPEN_BOOKINGS": 409,
    "ERR_NO_COMP_CARD": 409,
    "ERR_SLOT_OVERLAP": 409,
    "ERR_HOLD_OVERLAP": 409,
    "ERR_MAX_NEGOTIATION_ROUNDS": 409,
    "ERR_ESCROW_INSUFFICIENT": 409,
    "ERR_NO_RESIDUAL_DUE": 409,
}

_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or malformed authentication headers.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not permitted for this operation.",
    "ERR_NOT_FOUND": "A referenced resource does not exist.",
    "ERR_INVALID_REQUEST": "The request body is missing required fields or has invalid values.",
    "ERR_INVALID_DATE_RANGE": "The supplied date range is invalid.",
    "ERR_STALE_TALENT_VERSION": "The expected talent version does not match the current version.",
    "ERR_INVALID_STATE": "The resource is not in a valid state for this transition.",
    "ERR_CROSS_ENTITY_GATE": "A referenced sibling entity is not in the required state.",
    "ERR_DEAL_NOT_ACCEPTED": "The deal memo must be ACCEPTED to confirm this booking.",
    "ERR_SUBMISSION_NOT_OFFERABLE": "The submission must be OFFER_EXTENDED to extend an offer.",
    "ERR_AUDITION_NOT_COMPLETED": "A completed audition slot is required before a callback.",
    "ERR_BOOKING_NOT_COMPLETED": "The booking must be COMPLETED before payment.",
    "ERR_CASTING_CALL_NOT_OPEN": "The casting call must be OPEN.",
    "ERR_TALENT_NOT_ROSTERED": "The talent must be ROSTERED.",
    "ERR_HOLD_NOT_ACTIVE": "The availability hold must be an ACTIVE CONFIRMED_BOOKING hold.",
    "ERR_TALENT_MISMATCH": "The payment talent does not match the booking talent.",
    "ERR_SLOT_NOT_ENDED": "The slot has not ended yet.",
    "ERR_BOOKING_NOT_ENDED": "The booking has not ended yet.",
    "ERR_BOOKING_ALREADY_PAID": "The booking has already been paid and cannot be cancelled.",
    "ERR_TALENT_HAS_OPEN_BOOKINGS": "The talent has open bookings and cannot be archived.",
    "ERR_NO_COMP_CARD": "The talent has no comp card on file.",
    "ERR_SLOT_OVERLAP": "The slot overlaps another scheduled slot on this director's calendar.",
    "ERR_HOLD_OVERLAP": "The hold overlaps another active hold of the same kind.",
    "ERR_MAX_NEGOTIATION_ROUNDS": "The negotiation has reached the maximum number of rounds.",
    "ERR_ESCROW_INSUFFICIENT": "The agency escrow balance is insufficient to release this commission.",
    "ERR_NO_RESIDUAL_DUE": "No residual amount is due.",
}
