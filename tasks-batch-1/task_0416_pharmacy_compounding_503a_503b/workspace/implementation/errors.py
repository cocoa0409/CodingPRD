"""Error catalogue and the ApiError exception type.

The HTTP status for each error_id is read straight from the PRD §5 error code
catalogue. error_id + http_status + message are carried on the exception and the
error handler renders them into the standard error envelope.
"""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else ERROR_HTTP_STATUS.get(error_id, 400)
        self.message = message or error_id


# PRD §5 Error Code Catalogue.
ERROR_HTTP_STATUS = {
    # Auth
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 401,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    # Not found
    "ERR_FACILITY_NOT_FOUND": 404,
    "ERR_MFR_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_PRESCRIPTION_NOT_FOUND": 404,
    "ERR_BATCH_NOT_FOUND": 404,
    "ERR_QC_TEST_NOT_FOUND": 404,
    "ERR_FINISHED_PREPARATION_NOT_FOUND": 404,
    "ERR_RECALL_NOT_FOUND": 404,
    "ERR_ENVIRONMENTAL_LOG_NOT_FOUND": 404,
    "ERR_REFERENCED_RESOURCE_NOT_FOUND": 422,
    # Input validation
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_ENUM_VALUE": 400,
    "ERR_INVALID_PAGINATION": 400,
    # State
    "ERR_BATCH_NOT_IN_STATE": 409,
    "ERR_BATCH_NOT_RELEASED": 409,
    "ERR_QC_NOT_IN_STATE": 409,
    "ERR_RECALL_NOT_IN_STATE": 409,
    "ERR_PRESCRIPTION_NOT_ACTIVE": 409,
    "ERR_MFR_RETIRED": 409,
    # OCC
    "ERR_STALE_VERSION": 412,
    # Business: segregation / QC / environmental
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_QC_INCOMPLETE": 409,
    "ERR_QC_FAILED": 409,
    "ERR_ENVIRONMENTAL_EXCURSION": 409,
    # Business: constraints
    "ERR_NO_INGREDIENTS_CHARGED": 409,
    "ERR_LOT_NOT_AVAILABLE": 409,
    "ERR_LOT_INSUFFICIENT_GRAMS": 409,
    "ERR_PURPOSE_PRESCRIPTION_MISMATCH": 422,
    "ERR_YIELD_OUT_OF_RANGE": 422,
    "ERR_BEYOND_USE_DATE_PASSED": 409,
    "ERR_DISPENSE_CHANNEL_MISMATCH": 422,
    "ERR_UNIT_NOT_RELEASED": 409,
    "ERR_UNIT_NOT_IN_INVENTORY": 409,
    "ERR_BATCH_HAS_DISPENSED_UNITS": 409,
    "ERR_PRESCRIPTION_HAS_DISPENSES": 409,
    # Business: fiscal / quota
    "ERR_ANTICIPATORY_LIMIT_EXCEEDED": 409,
    "ERR_RECALL_UNITS_OUTSTANDING": 409,
}
