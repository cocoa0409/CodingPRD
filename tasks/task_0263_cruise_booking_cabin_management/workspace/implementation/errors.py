"""Error definitions: each error_id maps to its HTTP status (PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


# error_id -> HTTP status code (PRD §5 Error Code Catalogue)
ERROR_STATUS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_NOT_BOOKING_OWNER": 403,
    "ERR_INVALID_STATE": 409,
    "ERR_SAILING_NOT_BOOKABLE": 409,
    "ERR_SAILING_NOT_DEPARTABLE": 409,
    "ERR_SAILING_NOT_DEPARTED": 409,
    "ERR_NO_INVENTORY": 409,
    "ERR_INSUFFICIENT_INVENTORY": 409,
    "ERR_NO_GUESTS": 409,
    "ERR_OCCUPANCY_EXCEEDED": 422,
    "ERR_DEPOSIT_NOT_SATISFIED": 402,
    "ERR_BALANCE_OUTSTANDING": 402,
    "ERR_BOOKING_INACTIVE": 409,
    "ERR_GROUP_BLOCK_NOT_HELD": 409,
    "ERR_BLOCK_HAS_BOOKINGS": 409,
    "ERR_TIME_WINDOW_CONFLICT": 409,
    "ERR_FOLIO_OUTSTANDING": 402,
    "ERR_DUPLICATE_CATEGORY_CODE": 409,
    "ERR_DUPLICATE_CABIN_NUMBER": 409,
    "ERR_DECK_OUT_OF_RANGE": 422,
    "ERR_STALE_SAILING_VERSION": 412,
}

_DEFAULT_MESSAGES = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": "Missing or invalid user context header.",
    "ERR_FORBIDDEN_FOR_ROLE": "Caller role is not permitted for this endpoint.",
    "ERR_NOT_FOUND": "A referenced resource does not exist.",
    "ERR_INVALID_REQUEST": "The request body is malformed or invalid.",
    "ERR_NOT_BOOKING_OWNER": "GuestUser is not the owner of this booking.",
    "ERR_INVALID_STATE": "The resource is not in a valid state for this operation.",
    "ERR_SAILING_NOT_BOOKABLE": "The sailing is not in a bookable status for this operation.",
    "ERR_SAILING_NOT_DEPARTABLE": "The sailing cannot depart before its embark date.",
    "ERR_SAILING_NOT_DEPARTED": "The sailing has not departed.",
    "ERR_NO_INVENTORY": "The sailing has no cabin inventory to open.",
    "ERR_INSUFFICIENT_INVENTORY": "Not enough cabins to satisfy this request.",
    "ERR_NO_GUESTS": "The booking has no guests.",
    "ERR_OCCUPANCY_EXCEEDED": "Occupancy exceeds the allowed maximum.",
    "ERR_DEPOSIT_NOT_SATISFIED": "A captured deposit equal to deposit_due_cents is required.",
    "ERR_BALANCE_OUTSTANDING": "An outstanding balance prevents this operation.",
    "ERR_BOOKING_INACTIVE": "The booking is cancelled or expired.",
    "ERR_GROUP_BLOCK_NOT_HELD": "The group block is not in a held status.",
    "ERR_BLOCK_HAS_BOOKINGS": "The group block has materialized bookings.",
    "ERR_TIME_WINDOW_CONFLICT": "The requested time window conflicts with an existing reservation.",
    "ERR_FOLIO_OUTSTANDING": "The folio balance is not zero.",
    "ERR_DUPLICATE_CATEGORY_CODE": "The cabin category code is already used on this sailing.",
    "ERR_DUPLICATE_CABIN_NUMBER": "The cabin number is already used on this sailing.",
    "ERR_DECK_OUT_OF_RANGE": "The deck is outside the category range.",
    "ERR_STALE_SAILING_VERSION": "expected_sailing_version does not match the sailing's current version.",
}
