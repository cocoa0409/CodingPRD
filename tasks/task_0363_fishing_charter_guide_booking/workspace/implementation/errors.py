"""Error catalog and the ApiError exception class.

Every error_id below maps to the exact HTTP status from PRD section 5.
"""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id
        super().__init__(self.message)


# error_id -> HTTP status (PRD section 5 catalog, verbatim)
ERROR_HTTP = {
    # auth
    "ERR_MISSING_USER_CONTEXT": 400,
    "ERR_FORBIDDEN_ROLE": 403,
    # existence
    "ERR_MARINA_NOT_FOUND": 404,
    "ERR_BOAT_NOT_FOUND": 404,
    "ERR_CAPTAIN_NOT_FOUND": 404,
    "ERR_MATE_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_CHARTER_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_SLOT_NOT_FOUND": 404,
    "ERR_RESERVATION_NOT_FOUND": 404,
    "ERR_ADDON_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_CATCH_REPORT_NOT_FOUND": 404,
    # request validation
    "ERR_INVALID_REQUEST": 400,
    # state
    "ERR_CHARTER_NOT_SCHEDULED": 409,
    "ERR_CHARTER_NOT_ON_HOLD": 409,
    "ERR_CHARTER_NOT_SAILED": 409,
    "ERR_CHARTER_NOT_CANCELLABLE": 409,
    "ERR_CHARTER_NOT_BOOKABLE": 409,
    "ERR_CHARTER_ALREADY_SAILED": 409,
    "ERR_BOOKING_NOT_RESERVED": 409,
    "ERR_BOOKING_NOT_CANCELLABLE": 409,
    "ERR_ADDON_BOOKING_NOT_FULFILLABLE": 409,
    "ERR_DEPART_TIME_NOT_REACHED": 409,
    "ERR_NO_BOOKINGS_TO_SAIL": 409,
    "ERR_CREW_NOT_LOCKED": 409,
    "ERR_NO_CAPTAIN_ASSIGNED": 409,
    "ERR_NO_MATE_ASSIGNED": 409,
    "ERR_NO_SLOT_RESERVED": 409,
    "ERR_PERMIT_REQUIRED": 409,
    "ERR_BOAT_NOT_IN_SERVICE": 409,
    "ERR_MARINA_NOT_OPEN": 409,
    # referential
    "ERR_CROSS_MARINA_MISMATCH": 409,
    # safety
    "ERR_CAPTAIN_UNQUALIFIED": 422,
    "ERR_CREDENTIAL_EXPIRED_FOR_DATE": 422,
    "ERR_MATE_NOT_OFFSHORE_CERTIFIED": 422,
    "ERR_BOAT_NOT_OFFSHORE_RATED": 422,
    "ERR_SLOT_LENGTH_EXCEEDED": 422,
    "ERR_BAG_LIMIT_EXCEEDED": 422,
    # temporal
    "ERR_SLOT_WINDOW_CONFLICT": 409,
    "ERR_CAPTAIN_DOUBLE_BOOKED": 409,
    # capacity / fiscal
    "ERR_CAPACITY_EXCEEDED": 409,
    "ERR_DEPOSIT_UNDERPAID": 402,
    # concurrency
    "ERR_STALE_CHARTER_VERSION": 412,
    # slot decommission
    "ERR_SLOT_DECOMMISSIONED": 409,
}
