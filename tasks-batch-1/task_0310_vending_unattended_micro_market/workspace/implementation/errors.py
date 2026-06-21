"""Error classes and error ID -> HTTP status catalog (from PRD section 5 / scaffold 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status if http_status is not None else ERROR_STATUS.get(error_id, 400)


# error_id -> HTTP status
ERROR_STATUS = {
    # auth
    "ERR_MISSING_OR_INVALID_USER_CONTEXT": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    # input
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_ENUM": 422,
    "ERR_INVALID_SLOT_CONFIG": 422,
    "ERR_DUPLICATE_SKU": 422,
    "ERR_DUPLICATE_ASSET_TAG": 422,
    # not found
    "ERR_HOST_SITE_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_MACHINE_NOT_FOUND": 404,
    "ERR_SLOT_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_DRIVER_NOT_FOUND": 404,
    "ERR_ROUTE_NOT_FOUND": 404,
    "ERR_STOP_NOT_FOUND": 404,
    "ERR_VISIT_NOT_FOUND": 404,
    "ERR_SALE_NOT_FOUND": 404,
    "ERR_STATEMENT_NOT_FOUND": 404,
    "ERR_TICKET_NOT_FOUND": 404,
    # state
    "ERR_VISIT_NOT_DRAFT": 409,
    "ERR_ROUTE_NOT_DISPATCHED": 409,
    "ERR_ROUTE_EMPTY": 409,
    "ERR_STOPS_UNRESOLVED": 409,
    "ERR_DRIVER_INACTIVE": 409,
    "ERR_STATEMENT_NOT_OPEN": 409,
    "ERR_VISITS_PENDING": 409,
    "ERR_SALE_NOT_SETTLED": 409,
    "ERR_TICKET_NOT_OPEN": 409,
    "ERR_TICKET_NOT_REOPENED": 409,
    "ERR_TICKET_NOT_IN_PROGRESS": 409,
    "ERR_TICKET_NOT_RESOLVED": 409,
    # business
    "ERR_MACHINE_FROZEN": 409,
    "ERR_SLOT_NOT_ON_MACHINE": 409,
    "ERR_PRODUCT_DISCONTINUED": 409,
    "ERR_SLOT_OVERFILL": 422,
    "ERR_INSUFFICIENT_STOCK": 409,
    "ERR_DRIVER_WINDOW_OVERLAP": 409,
    "ERR_STATEMENT_PERIOD_OVERLAP": 409,
    "ERR_HOST_SUSPENDED": 409,
    # concurrency
    "ERR_STALE_MACHINE_VERSION": 412,
}
