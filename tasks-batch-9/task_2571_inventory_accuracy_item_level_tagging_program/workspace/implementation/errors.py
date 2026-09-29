"""Error catalog (PRD Section 5) and the ApiError exception."""

ERROR_STATUS = {
    # --- authentication / authorization ---
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_IDENTITY_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_ADJUSTMENT_ABOVE_SUPERVISOR_CAP": 403,
    # --- existence (404 family) ---
    "ERR_CATEGORY_NOT_FOUND": 404,
    "ERR_STORE_NOT_FOUND": 404,
    "ERR_VENDOR_NOT_FOUND": 404,
    "ERR_COUNTER_FIRM_NOT_FOUND": 404,
    "ERR_ITEM_NOT_FOUND": 404,
    "ERR_STOCK_POSITION_NOT_FOUND": 404,
    "ERR_TAG_BATCH_NOT_FOUND": 404,
    "ERR_COUNT_SCHEDULE_NOT_FOUND": 404,
    "ERR_COUNT_TASK_NOT_FOUND": 404,
    "ERR_COUNT_LINE_NOT_FOUND": 404,
    "ERR_INVESTIGATION_NOT_FOUND": 404,
    "ERR_ADJUSTMENT_NOT_FOUND": 404,
    "ERR_SHRINK_PERIOD_NOT_FOUND": 404,
    "ERR_PHYSICAL_INVENTORY_NOT_FOUND": 404,
    "ERR_PHYSICAL_INVENTORY_LINE_NOT_FOUND": 404,
    # --- shape / uniqueness ---
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_ENUM_VALUE": 422,
    "ERR_INVALID_PAGINATION": 422,
    "ERR_DUPLICATE_CATEGORY_CODE": 409,
    "ERR_DUPLICATE_STORE_CODE": 409,
    "ERR_DUPLICATE_VENDOR_CODE": 409,
    "ERR_DUPLICATE_COUNTER_FIRM_CODE": 409,
    "ERR_DUPLICATE_SKU": 409,
    # --- optimistic concurrency ---
    "ERR_STALE_STOCK_POSITION_VERSION": 412,
    "ERR_STALE_PHYSICAL_INVENTORY_VERSION": 412,
    "ERR_STALE_INVESTIGATION_VERSION": 412,
    # --- state preconditions ---
    "ERR_TAG_BATCH_INVALID_STATE": 409,
    "ERR_COUNT_TASK_INVALID_STATE": 409,
    "ERR_INVESTIGATION_INVALID_STATE": 409,
    "ERR_ADJUSTMENT_INVALID_STATE": 409,
    "ERR_SHRINK_PERIOD_INVALID_STATE": 409,
    "ERR_PHYSICAL_INVENTORY_INVALID_STATE": 409,
    "ERR_COUNT_SCHEDULE_NOT_ACTIVE": 409,
    # --- compliance ---
    "ERR_TAG_INTEGRITY_HOLD": 409,
    "ERR_SHRINK_PERIOD_STILL_OPEN": 409,
    # --- referential coupling ---
    "ERR_INVESTIGATION_NOT_CLOSED": 409,
    "ERR_ITEM_CATEGORY_MISMATCH": 409,
    "ERR_ITEM_NOT_STOCKED_AT_STORE": 409,
    "ERR_NO_COVERING_SHRINK_PERIOD": 409,
    "ERR_OPEN_INVESTIGATIONS": 409,
    # --- geometric / cardinality ---
    "ERR_READER_MODE_UNSUPPORTED": 422,
    "ERR_CATEGORY_READER_MODE_MISMATCH": 422,
    "ERR_COUNT_WINDOW_OVERLAP": 409,
    "ERR_OVERHEAD_READER_CAPACITY_EXCEEDED": 409,
    "ERR_PHYSICAL_INVENTORY_BLACKOUT_CONFLICT": 409,
    "ERR_SHRINK_PERIOD_OVERLAP": 409,
    "ERR_DUPLICATE_STOCK_POSITION": 409,
    "ERR_DUPLICATE_COUNT_LINE": 409,
    "ERR_ZERO_DELTA_UNITS": 422,
    "ERR_REWORK_LIMIT_REACHED": 409,
    "ERR_TAG_SCHEME_MISMATCH": 422,
    "ERR_SAMPLE_BELOW_REQUIRED": 422,
    "ERR_INVALID_VERIFICATION_COUNTS": 422,
    "ERR_NO_COUNT_LINES": 409,
    "ERR_COUNT_COVERAGE_BELOW_MIN": 409,
    "ERR_MAX_LINES_PER_PASS_EXCEEDED": 409,
    # --- temporal ---
    "ERR_COUNT_WINDOW_NOT_DUE": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_INVALID_PERIOD_RANGE": 422,
    # --- fiscal ---
    "ERR_ADJUSTMENT_APPROVAL_REQUIRED": 409,
    "ERR_RECOUNT_REQUIRED": 409,
    "ERR_NO_VENDOR_SHORTAGE": 409,
    "ERR_CHARGEBACK_ALREADY_ISSUED": 409,
    "ERR_CREDIT_EXCEEDS_BALANCE": 422,
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline; converted to the error envelope."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = ERROR_STATUS.get(error_id, 422)


def _default_message(error_id):
    body = error_id[4:] if error_id.startswith("ERR_") else error_id
    return body.replace("_", " ").lower().capitalize()


def fail(error_id, message=None):
    raise ApiError(error_id, message)
