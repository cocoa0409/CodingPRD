"""Error catalogue (PRD §5) and the ApiError exception type."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status for every error_id in the catalogue (PRD §5).
ERROR_HTTP = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_VALIDATION": 422,
    "ERR_INVALID_LINE_QUANTITY": 409,
    "ERR_LINE_TYPE_MISMATCH": 409,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_SALON_NOT_FOUND": 404,
    "ERR_TICKET_NOT_FOUND": 404,
    "ERR_VISIT_NOT_FOUND": 404,
    "ERR_CHAIR_NOT_FOUND": 404,
    "ERR_TECHNICIAN_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_PACKAGE_NOT_FOUND": 404,
    "ERR_LINE_NOT_FOUND": 404,
    "ERR_SERVICE_ITEM_NOT_FOUND": 404,
    "ERR_ADDON_NOT_FOUND": 404,
    "ERR_RETAIL_NOT_FOUND": 404,
    "ERR_SALON_NOT_OPEN": 409,
    "ERR_TICKET_NOT_CALLED": 409,
    "ERR_VISIT_NOT_IN_SERVICE": 409,
    "ERR_VISIT_NOT_COMPLETED": 409,
    "ERR_VISIT_NOT_UNPAID": 409,
    "ERR_VISIT_ALREADY_VOIDED": 409,
    "ERR_CHAIR_NOT_OPEN": 409,
    "ERR_CHAIR_OCCUPIED": 409,
    "ERR_TECHNICIAN_NOT_AVAILABLE": 409,
    "ERR_MEMBER_NOT_ACTIVE": 409,
    "ERR_RECALL_LIMIT_REACHED": 409,
    "ERR_LICENSE_LAPSED": 403,
    "ERR_TECH_CERT_EXPIRED": 403,
    "ERR_MEMBER_BLOCKED": 403,
    "ERR_TECH_NOT_CERTIFIED": 409,
    "ERR_CHAIR_NOT_SANITIZED": 409,
    "ERR_SANITATION_WINDOW_OPEN": 409,
    "ERR_QUEUE_ORDER_VIOLATION": 409,
    "ERR_INSUFFICIENT_STOCK": 409,
    "ERR_SALON_HAS_ACTIVE_VISITS": 409,
    "ERR_INSUFFICIENT_LOYALTY": 402,
    "ERR_STALE_SALON_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP[error_id], message)
