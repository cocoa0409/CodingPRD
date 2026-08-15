"""Error classes and the error catalogue (PRD Section 5 / scaffold Section 1.6).

Every error_id and its HTTP status is taken verbatim from the PRD error code
catalogue and the scaffold error table.
"""


class ApiError(Exception):
    """A domain error carrying a machine-readable error_id and HTTP status.

    The error body uses the exact envelope field names: data.error_id and
    data.message (PRD Section 2.2).
    """

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalogue (PRD Section 5 / scaffold Section 1.6) -------------------
ERROR_STATUS = {
    "ERR_MISSING_AUTH_CONTEXT": 400,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_ENUM": 422,
    "ERR_RANGE_INVALID": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_STORE_MANAGER_MISMATCH": 403,
    "ERR_DRIVER_NOT_ASSIGNED": 403,
    "ERR_SOD_CERTIFIER_IS_COUNTER": 403,
    "ERR_SOD_APPROVER_IS_CREATOR": 403,
    "ERR_AGREEMENT_EXISTS": 409,
    "ERR_AGREEMENT_NOT_ACTIVE": 409,
    "ERR_SKU_EXISTS": 409,
    "ERR_DUPLICATE_SCAN_EVENT": 409,
    "ERR_VOID_TARGET_INVALID": 409,
    "ERR_WINDOW_INVALID": 422,
    "ERR_VISIT_WINDOW_CLOSED": 409,
    "ERR_SEASONAL_WINDOW_NOT_OPEN": 409,
    "ERR_SEASONAL_ALLOCATION_MISSING": 409,
    "ERR_SETTLEMENT_PERIOD_NOT_CLOSED": 409,
    "ERR_SETTLEMENT_ALREADY_EXISTS": 409,
    "ERR_AUDIT_NOT_CERTIFIED": 409,
    "ERR_PAYOUT_BELOW_MINIMUM": 409,
    "ERR_RESTOCK_VALUE_CAP_EXCEEDED": 409,
    "ERR_MARKDOWN_CAP_EXCEEDED": 409,
    "ERR_SPACE_WINDOW_OVERLAP": 409,
    "ERR_CATEGORY_EXCLUSIVE_CONFLICT": 409,
    "ERR_SPACE_CAPACITY_EXCEEDED": 422,
    "ERR_PROMO_GAP_VIOLATION": 409,
    "ERR_PRICE_BELOW_FLOOR": 422,
    "ERR_PRODUCT_NOT_IN_PROGRAM": 422,
    "ERR_PRODUCT_DISCONTINUED": 409,
    "ERR_ROUTE_PROGRAM_MISMATCH": 422,
}


def err(error_id, message=None):
    """Construct an ApiError, looking the http status up from the catalogue."""
    return ApiError(error_id, ERROR_STATUS[error_id], message)
