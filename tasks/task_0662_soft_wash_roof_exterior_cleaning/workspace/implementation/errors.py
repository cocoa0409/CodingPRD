"""Error class and error-id -> HTTP status catalog (SCAFFOLD §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or error_id


ERROR_STATUS = {
    # Auth
    "ERR_MISSING_AUTH_HEADER": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    # Validation
    "ERR_INVALID_REQUEST": 400,
    # Not found
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_TECHNICIAN_NOT_FOUND": 404,
    "ERR_ROUTE_NOT_FOUND": 404,
    "ERR_PROPERTY_NOT_FOUND": 404,
    "ERR_QUOTE_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_VISIT_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_WEATHER_WINDOW_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    # State
    "ERR_INVALID_STATE": 409,
    "ERR_QUOTE_EMPTY": 409,
    "ERR_QUOTE_NOT_ACCEPTED": 409,
    "ERR_NO_CONFIRMED_CREW": 409,
    "ERR_BEFORE_PHOTO_MISSING": 409,
    "ERR_AFTER_PHOTO_MISSING": 409,
    # Weather / scheduling
    "ERR_NO_CLEAR_WEATHER": 409,
    "ERR_WEATHER_WINDOW_OVERLAP": 409,
    # Safety
    "ERR_TECH_NOT_ASSIGNABLE": 403,
    "ERR_TECH_DOUBLE_BOOKED": 409,
    # Fiscal
    "ERR_CREDIT_LIMIT_EXCEEDED": 402,
    # Concurrency
    "ERR_STALE_VERSION": 412,
}
