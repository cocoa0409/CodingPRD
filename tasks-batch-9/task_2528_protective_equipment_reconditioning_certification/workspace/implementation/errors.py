"""Error catalogue (PRD 5) and the exception type every rejection raises."""

ERROR_STATUS = {
    # auth / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_ACCOUNT_SCOPE_VIOLATION": 403,
    # schema
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_CUSTOMER_ACCOUNT_NOT_FOUND": 404,
    "ERR_MODEL_SPEC_NOT_FOUND": 404,
    "ERR_APPROVED_PART_NOT_FOUND": 404,
    "ERR_TEST_BENCH_NOT_FOUND": 404,
    "ERR_SHIPMENT_NOT_FOUND": 404,
    "ERR_UNIT_NOT_FOUND": 404,
    "ERR_SHELL_TEST_NOT_FOUND": 404,
    "ERR_REPAIR_ORDER_NOT_FOUND": 404,
    "ERR_LABEL_NOT_FOUND": 404,
    "ERR_DESTRUCTION_RECORD_NOT_FOUND": 404,
    "ERR_LOANER_UNIT_NOT_FOUND": 404,
    "ERR_LOANER_ASSIGNMENT_NOT_FOUND": 404,
    # state
    "ERR_SHIPMENT_STATE_INVALID": 409,
    "ERR_UNIT_STATE_INVALID": 409,
    "ERR_SHELL_TEST_STATE_INVALID": 409,
    "ERR_REPAIR_ORDER_STATE_INVALID": 409,
    "ERR_LABEL_ALREADY_VOIDED": 409,
    "ERR_DESTRUCTION_STATE_INVALID": 409,
    "ERR_LOANER_ASSIGNMENT_STATE_INVALID": 409,
    # business safety
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CONDEMN_REQUIRED": 422,
    "ERR_DETERMINATION_MISMATCH": 422,
    "ERR_DETERMINATION_UPGRADE_FORBIDDEN": 422,
    "ERR_PART_NOT_APPROVED": 422,
    "ERR_PART_MODEL_MISMATCH": 422,
    "ERR_MODEL_NOT_RECONDITIONABLE": 422,
    "ERR_BENCH_CALIBRATION_EXPIRED": 409,
    "ERR_INSPECTION_INCOMPLETE": 409,
    "ERR_DUPLICATE_INSPECTION": 409,
    # business constraints
    "ERR_UNIT_COUNT_EXCEEDED": 409,
    "ERR_UNIT_REGISTRATION_INCOMPLETE": 409,
    "ERR_SERIAL_DUPLICATE": 409,
    "ERR_RETEST_LIMIT_EXCEEDED": 409,
    "ERR_PART_STOCK_INSUFFICIENT": 409,
    # business temporal
    "ERR_BENCH_WINDOW_CONFLICT": 409,
    "ERR_BENCH_DAILY_QUOTA_EXCEEDED": 409,
    "ERR_LOANER_DOUBLE_BOOKED": 409,
    "ERR_LOANER_CERTIFICATION_EXPIRED": 422,
    "ERR_NO_LOANER_AVAILABLE": 409,
    "ERR_LABEL_WINDOW_EXPIRED": 422,
    "ERR_RETENTION_ACTIVE": 409,
    # business referential
    "ERR_LIABILITY_WAIVER_MISSING": 409,
    "ERR_WARRANTY_CLAIM_REQUIRED": 422,
    # business fiscal
    "ERR_ACCOUNT_ON_HOLD": 402,
    "ERR_SHIPMENT_NOT_READY": 409,
    "ERR_SETTLEMENT_LOCKED": 409,
    # concurrency
    "ERR_STALE_UNIT_VERSION": 412,
    # transport-level fallbacks (not part of the PRD catalogue)
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or incomplete.",
    "ERR_UNAUTHORIZED": "The acting role is not authorized for this endpoint.",
    "ERR_ACCOUNT_SCOPE_VIOLATION": "The requested resource belongs to another customer account.",
    "ERR_INVALID_REQUEST": "The request payload failed schema validation.",
    "ERR_SEGREGATION_OF_DUTIES": "This step must be performed by a different user.",
    "ERR_STALE_UNIT_VERSION": "The expected equipment unit version does not match.",
}


class ApiError(Exception):
    """A rejection carrying an error_id from the PRD 5 catalogue."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
