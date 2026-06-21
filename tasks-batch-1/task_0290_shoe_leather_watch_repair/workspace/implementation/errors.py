"""Error classes and the error catalogue (id -> HTTP status)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status if http_status is not None else ERROR_STATUS.get(error_id, 400)


# Full error catalogue from PRD §5 / scaffold §1.6
ERROR_STATUS = {
    # Auth
    "ERR_MISSING_AUTH_CONTEXT": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_TICKET_OWNER": 403,
    "ERR_SEGREGATION_VIOLATION": 403,
    # Not found
    "ERR_TICKET_NOT_FOUND": 404,
    "ERR_ESTIMATE_NOT_FOUND": 404,
    "ERR_PARTS_ORDER_NOT_FOUND": 404,
    "ERR_SERVICE_LINE_NOT_FOUND": 404,
    "ERR_TICKET_ITEM_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_SERVICE_TYPE_NOT_FOUND": 404,
    # Request validation
    "ERR_INVALID_REQUEST": 400,
    "ERR_FK_NOT_FOUND": 422,
    "ERR_DUPLICATE_KEY": 409,
    # State
    "ERR_INVALID_TICKET_STATE": 409,
    "ERR_INVALID_ESTIMATE_STATE": 409,
    "ERR_INVALID_PARTS_STATE": 409,
    "ERR_INVALID_CLAIM_STATE": 409,
    "ERR_STALE_TICKET_VERSION": 412,
    "ERR_NO_SERVICE_LINES": 409,
    "ERR_BAD_REVISION_CHAIN": 409,
    "ERR_PARTS_NOT_READY": 409,
    "ERR_NO_TECHNICIAN": 409,
    "ERR_LINES_NOT_COMPLETED": 409,
    "ERR_NOT_CANCELLABLE": 409,
    "ERR_PAYMENT_NOT_REFUNDABLE": 409,
    # Temporal / unclaimed / warranty
    "ERR_UNCLAIMED_TOO_EARLY": 409,
    "ERR_DISPOSAL_TOO_EARLY": 409,
    "ERR_UNCLAIMED_NOT_WARNED": 409,
    "ERR_WARRANTY_EXPIRED": 422,
    # Fiscal
    "ERR_BALANCE_DUE": 402,
}
