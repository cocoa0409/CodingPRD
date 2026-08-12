"""Error classes and error ID constants from the scaffold error catalog."""


class ApiError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error HTTP status map (from SCAFFOLD Table 6)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_ASSIGNEE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_ENUM": 400,
    "ERR_INVALID_MEASUREMENT": 422,
    "ERR_MARKET_MISMATCH": 422,
    "ERR_SERVICE_NOT_PATROL": 422,
    "ERR_VISIT_WINDOW_PAST": 422,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_OFFER_EXPIRED": 409,
    "ERR_VISIT_NOT_DUE": 409,
    "ERR_NOTIFICATION_PENDING": 409,
    "ERR_NOTIFICATION_DEADLINE_EXPIRED": 409,
    "ERR_PERMIT_NOT_APPROVED": 409,
    "ERR_DOCS_INCOMPLETE": 409,
    "ERR_PACKAGE_LOCKED": 409,
    "ERR_HAZARD_NOT_MITIGATED": 409,
    "ERR_SCOPE_EMPTY": 422,
    "ERR_SCOPE_ITEMS_PENDING": 409,
    "ERR_NO_COVERAGE": 409,
    "ERR_CAPACITY_FULL": 409,
    "ERR_SUBCONTRACTOR_SUSPENDED": 409,
    "ERR_DUPLICATE_COVERAGE": 409,
    "ERR_DUPLICATE_PACKAGE": 409,
    "ERR_PERMIT_CASE_OPEN": 409,
    "ERR_INVOICE_OPEN_EXISTS": 409,
    "ERR_INVOICE_VARIANT_INVALID": 409,
    "ERR_OVERLAP_CONFLICT": 409,
    "ERR_GENERATOR_POOL_EXHAUSTED": 409,
    "ERR_SERVICES_STILL_ACTIVE": 409,
    "ERR_VARIANCE_CAP_EXCEEDED": 409,
    "ERR_INVOICES_UNPAID": 409,
}


def err(error_id: str, message: str = "") -> ApiError:
    return ApiError(error_id, message or error_id, ERROR_STATUS[error_id])
