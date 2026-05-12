"""Error definitions and exceptions."""


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error catalog: error_id -> http_status
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_MISMATCH": 409,
    "ERR_TENANT_NOT_APPROVED": 409,
    "ERR_LICENSE_EXPIRED": 409,
    "ERR_DUPLICATE_LICENSE": 409,
    "ERR_UNIT_NOT_AVAILABLE": 409,
    "ERR_LEASE_OVERLAP": 409,
    "ERR_RENOVATION_LEASE_CONFLICT": 409,
    "ERR_INVALID_DATE_RANGE": 422,
    "ERR_STEPPED_SCHEDULE_INVALID": 422,
    "ERR_LEASE_DEPENDENCY": 409,
    "ERR_DEPOSIT_INCOMPLETE": 409,
    "ERR_DEPOSIT_OVERPAY": 409,
    "ERR_DEDUCTION_EXCEEDS_DEPOSIT": 409,
    "ERR_DEPOSIT_NOT_SETTLED": 409,
    "ERR_OUTSTANDING_FEE_BILL": 409,
    "ERR_LEASE_NOT_BILLABLE": 409,
    "ERR_LEASE_NOT_YET_STARTED": 409,
    "ERR_MOVE_OUT_LEAD_TIME": 409,
    "ERR_RENEWAL_WINDOW_NOT_OPEN": 409,
    "ERR_AREA_SUM_MISMATCH": 409,
    "ERR_UNIT_CODE_CONFLICT": 409,
    "ERR_MERGE_LAYOUT_INVALID": 409,
    "ERR_RESTORATION_INCOMPLETE": 409,
    "ERR_AMENDMENT_PAYLOAD_INVALID": 422,
    "ERR_TENANT_HAS_ACTIVE_LEASE": 409,
}


def err(error_id: str, message: str = "") -> APIError:
    """Construct an APIError using the catalog HTTP status."""
    return APIError(error_id, message or error_id, ERROR_CATALOG.get(error_id, 500))
