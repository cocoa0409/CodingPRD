"""Error classes and the full error catalog (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status per error id (PRD section 5 error catalog).
ERROR_HTTP = {
    # auth
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    # existence
    "ERR_CONTAINER_TYPE_NOT_FOUND": 404,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_CONTAINER_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_ROUTE_NOT_FOUND": 404,
    "ERR_STOP_NOT_FOUND": 404,
    "ERR_WEIGH_TICKET_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    # validation / input
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_DATE_RANGE": 422,
    "ERR_DUPLICATE_RESOURCE": 409,
    # state
    "ERR_ORDER_NOT_BOOKED": 409,
    "ERR_ORDER_NOT_SCHEDULED": 409,
    "ERR_ORDER_NOT_ON_SITE": 409,
    "ERR_ORDER_NOT_CANCELLABLE": 409,
    "ERR_STOP_NOT_UNASSIGNED": 409,
    "ERR_STOP_NOT_ASSIGNED": 409,
    "ERR_STOP_NOT_CANCELLABLE": 409,
    "ERR_ROUTE_NOT_PLANNING": 409,
    "ERR_ROUTE_NOT_DISPATCHED": 409,
    "ERR_ROUTE_EMPTY": 409,
    "ERR_ROUTE_HAS_OPEN_STOPS": 409,
    "ERR_ROUTE_AT_CAPACITY": 409,
    "ERR_CONTAINER_NOT_AVAILABLE": 409,
    "ERR_CONTAINER_NOT_AWAITING_DUMP": 409,
    "ERR_CONTAINER_NOT_OUT_OF_SERVICE": 409,
    "ERR_CONTAINER_TYPE_MISMATCH": 409,
    "ERR_PERMIT_NOT_REQUESTED": 409,
    "ERR_PERMIT_NOT_APPROVED": 409,
    "ERR_PERMIT_NOT_EXPIRED": 409,
    "ERR_PERMIT_WINDOW_PASSED": 409,
    "ERR_PERMIT_WINDOW_OVERLAP": 409,
    "ERR_INVOICE_NOT_ISSUED": 409,
    "ERR_WEIGH_TICKET_REQUIRED": 409,
    "ERR_ACCOUNT_SUSPENDED": 409,
    # fiscal
    "ERR_CREDIT_LIMIT_EXCEEDED": 402,
    # concurrency
    "ERR_STALE_CONTAINER_VERSION": 412,
    "ERR_STALE_ROUTE_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP[error_id], message)
