"""Error catalogue (PRD §5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_ORGANIZER_NOT_FOUND": 404,
    "ERR_VENUE_NOT_FOUND": 404,
    "ERR_BUYER_NOT_FOUND": 404,
    "ERR_EVENT_NOT_FOUND": 404,
    "ERR_TICKET_TYPE_NOT_FOUND": 404,
    "ERR_SEAT_BLOCK_NOT_FOUND": 404,
    "ERR_PROMO_CODE_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_ORDER_ITEM_NOT_FOUND": 404,
    "ERR_ATTENDEE_NOT_FOUND": 404,
    "ERR_SCAN_NOT_FOUND": 404,
    "ERR_REFUND_REQUEST_NOT_FOUND": 404,
    "ERR_TRANSFER_REQUEST_NOT_FOUND": 404,
    "ERR_WAITLIST_ENTRY_NOT_FOUND": 404,
    "ERR_PAYOUT_NOT_FOUND": 404,
    "ERR_EVENT_NOT_ONSALE": 409,
    "ERR_INVALID_EVENT_TRANSITION": 409,
    "ERR_ORDER_NOT_HELD": 409,
    "ERR_ORDER_NOT_PAID": 409,
    "ERR_INVALID_REFUND_STATE": 409,
    "ERR_INVALID_TRANSFER_STATE": 409,
    "ERR_INVALID_WAITLIST_STATE": 409,
    "ERR_INVALID_PAYOUT_STATE": 409,
    "ERR_ATTENDEE_NOT_ISSUED": 409,
    "ERR_VENUE_DOUBLE_BOOKED": 409,
    "ERR_HOLD_EXPIRED": 409,
    "ERR_PROMO_WINDOW_CLOSED": 409,
    "ERR_CHECKIN_WINDOW_CLOSED": 409,
    "ERR_REFUND_WINDOW_CLOSED": 409,
    "ERR_TRANSFER_TTL_EXPIRED": 409,
    "ERR_WAITLIST_OFFER_EXPIRED": 409,
    "ERR_RESERVE_NOT_MATURED": 409,
    "ERR_EVENT_NOT_ENDED": 409,
    "ERR_EVENT_START_IN_PAST": 422,
    "ERR_ATTENDEE_EVENT_MISMATCH": 422,
    "ERR_PROMO_EVENT_MISMATCH": 422,
    "ERR_TICKET_VOIDED": 409,
    "ERR_ALREADY_CHECKED_IN": 409,
    "ERR_SOD_SAME_ACTOR": 403,
    "ERR_SEAT_UNAVAILABLE": 409,
    "ERR_SEAT_RANGE_INVALID": 422,
    "ERR_TICKET_LIMIT_EXCEEDED": 409,
    "ERR_DUPLICATE_PROMO_CODE": 409,
    "ERR_SOLD_OUT": 409,
    "ERR_INSUFFICIENT_CAPACITY": 409,
    "ERR_CAPACITY_AVAILABLE": 409,
    "ERR_PROMO_NOT_APPLICABLE": 422,
    "ERR_PROMO_EXHAUSTED": 409,
    "ERR_REFUND_EXCEEDS_ORDER": 422,
    "ERR_PAYOUT_NOT_ELIGIBLE": 409,
    "ERR_PAYOUT_PENDING_REFUNDS": 409,
    "ERR_STALE_EVENT_VERSION": 412,
    "ERR_STALE_ORGANIZER_VERSION": 412,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers missing or role not recognised.",
    "ERR_UNAUTHORIZED": "The acting principal is not permitted to perform this operation.",
    "ERR_INVALID_REQUEST": "The request payload or query parameters are invalid.",
    "ERR_STALE_EVENT_VERSION": "expected_event_version does not match the event's current version.",
    "ERR_STALE_ORGANIZER_VERSION": "expected_organizer_version does not match the organizer's current version.",
}
