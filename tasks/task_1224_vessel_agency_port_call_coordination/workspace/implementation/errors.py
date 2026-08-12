"""Error types and the error catalog (error_id -> HTTP status)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_CONFIRM_ROLE_MISMATCH": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_BERTH_WINDOW_OVERLAP": 409,
    "ERR_RESOURCE_UNIT_OVERLAP": 409,
    "ERR_DUPLICATE_NOTIFICATION_TYPE": 409,
    "ERR_DUPLICATE_BL_NUMBER": 409,
    "ERR_INVALID_REQUEST": 400,
    "ERR_PRE_ARRIVAL_DEADLINE_MISSED": 422,
    "ERR_WINDOW_INVALID": 422,
    "ERR_WINDOW_NOT_STARTED": 422,
    "ERR_PASSPORT_EXPIRY_INVALID": 422,
    "ERR_SHORE_PASS_EXPIRED": 422,
    "ERR_NOTIFICATIONS_OUTSTANDING": 422,
    "ERR_HM_ACK_OUTSTANDING": 422,
    "ERR_BERTH_WINDOW_MISMATCH": 422,
    "ERR_BERTH_NOT_OCCUPIED": 422,
    "ERR_OPEN_CREW_CHANGES": 422,
    "ERR_CARGO_DOCS_ON_HOLD": 422,
    "ERR_BL_RELEASE_TOO_EARLY": 422,
    "ERR_FREIGHT_NOT_PAID": 422,
    "ERR_VISA_NOT_REQUIRED": 422,
    "ERR_VISA_REQUIRED": 422,
    "ERR_PORT_CALL_NOT_EDITABLE": 422,
    "ERR_PORT_CALL_NOT_SAILED": 422,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_DISPUTES_OPEN": 422,
    "ERR_DA_NOT_SETTLED": 422,
    "ERR_DA_NOT_SENT": 422,
    "ERR_NO_LINKED_CREW_CHANGE": 422,
    "ERR_PRINCIPAL_SUSPENDED": 422,
    "ERR_VENDOR_SUSPENDED": 422,
    "ERR_VENDOR_CATEGORY_MISMATCH": 422,
    "ERR_VENDOR_KIND_MISMATCH": 422,
    "ERR_FUNDING_SHORTFALL": 422,
    "ERR_CREDIT_LIMIT_EXCEEDED": 422,
    "ERR_UNREFUNDED_ADVANCES": 422,
    "ERR_BALANCE_NOT_ZERO": 422,
    "ERR_APPLY_EXCEEDS_REMAINING": 422,
    "ERR_OPEN_CRITICAL_HUSBANDRY": 422,
}


def raise_err(error_id, message):
    raise ApiError(error_id, message, ERROR_HTTP[error_id])


def not_found(what="resource"):
    raise_err("ERR_NOT_FOUND", "The requested %s does not exist" % what)


def invalid_state(msg="The state machine does not permit this transition"):
    raise_err("ERR_INVALID_STATE", msg)


def invalid_request(msg="Request body is missing required fields or has invalid values"):
    raise_err("ERR_INVALID_REQUEST", msg)
