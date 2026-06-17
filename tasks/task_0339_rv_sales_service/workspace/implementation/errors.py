"""Error classes and the complete error catalogue (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id -> http status
CATALOG = {
    # auth
    "ERR_MISSING_AUTH": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    # existence
    "ERR_DEALERSHIP_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_UNIT_NOT_FOUND": 404,
    "ERR_DEAL_NOT_FOUND": 404,
    "ERR_SERVICE_BAY_NOT_FOUND": 404,
    "ERR_SERVICE_ORDER_NOT_FOUND": 404,
    "ERR_PART_ITEM_NOT_FOUND": 404,
    "ERR_WARRANTY_PLAN_NOT_FOUND": 404,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    "ERR_STORAGE_SLOT_NOT_FOUND": 404,
    "ERR_RECALL_CAMPAIGN_NOT_FOUND": 404,
    # OCC / state
    "ERR_STALE_UNIT_VERSION": 412,
    "ERR_UNIT_NOT_AVAILABLE": 409,
    "ERR_DEAL_BAD_SALE_STATE": 409,
    "ERR_DEAL_TERMINAL": 409,
    "ERR_FINANCE_BAD_STATE": 409,
    "ERR_FINANCE_NOT_SETTLED": 409,
    "ERR_PDI_NOT_PASSED": 409,
    "ERR_SO_BAD_STATE": 409,
    "ERR_SO_TERMINAL": 409,
    "ERR_APPT_BAD_STATE": 409,
    "ERR_APPT_TERMINAL": 409,
    "ERR_STORAGE_BAD_STATE": 409,
    "ERR_RECALL_BAD_STATE": 409,
    "ERR_REMEDIES_OUTSTANDING": 409,
    "ERR_NOT_CONSIGNMENT": 409,
    # referential / business
    "ERR_CONSIGNOR_REQUIRED": 409,
    "ERR_CONSIGNOR_NOT_ALLOWED": 409,
    "ERR_WARRANTY_UNIT_MISMATCH": 409,
    "ERR_STOP_SALE_RECALL_OPEN": 409,
    # temporal / capacity
    "ERR_BAY_DOUBLE_BOOKED": 409,
    "ERR_STORAGE_OVERLAP": 409,
    "ERR_INSUFFICIENT_PARTS": 409,
    # fiscal
    "ERR_LTV_EXCEEDED": 402,
    "ERR_WARRANTY_CAP_EXCEEDED": 402,
    # input / uniqueness
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_INTERVAL": 400,
    "ERR_INVALID_RELEASE_TIME": 400,
    "ERR_INVALID_TERM": 400,
    "ERR_DOC_FEE_OVER_CAP": 400,
    "ERR_DUPLICATE_VIN": 409,
    "ERR_DUPLICATE_EMAIL": 409,
    "ERR_DUPLICATE_SKU": 409,
    "ERR_DUPLICATE_CAMPAIGN": 409,
}


def err(error_id, message=None):
    raise ApiError(error_id, CATALOG[error_id], message)
