"""Error catalog and ApiError exception. Error IDs and HTTP statuses come
straight from SCAFFOLD.yaml Table 6 / PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_NO_INSURANCE_COVERAGE": 409,
    "ERR_SUPERVISOR_REQUIRED": 409,
    "ERR_VENUE_DOUBLE_BOOKED": 409,
    "ERR_REFURBISHMENT_GAP_VIOLATED": 409,
    "ERR_WINDOW_MALFORMED": 422,
    "ERR_SPONSORSHIP_OVER_CAP": 409,
    "ERR_DUPLICATE_CONTRACT": 409,
    "ERR_ROUTE_NOT_CONSECUTIVE": 409,
    "ERR_CRATE_NOT_ON_SHIPMENT": 409,
    "ERR_CLAIM_AMOUNT_MISMATCH": 422,
    "ERR_CLAIM_EXCEEDS_COVERAGE": 409,
    "ERR_ATTENDANCE_MISSING": 409,
    "ERR_TOUR_NOT_RETIREABLE": 409,
    "ERR_INVALID_REQUEST": 400,
}


def fail(error_id, message):
    """Raise an ApiError using the catalogued HTTP status for error_id."""
    raise ApiError(error_id, ERROR_CATALOG[error_id], message)
