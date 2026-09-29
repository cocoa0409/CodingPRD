"""Error catalogue (PRD 5)."""

ERROR_HTTP = {
    # auth / shape
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_TERMINAL_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_TARIFF_VERSION_NOT_FOUND": 404,
    "ERR_COMMODITY_PROFILE_NOT_FOUND": 404,
    "ERR_RATE_PROGRAM_NOT_FOUND": 404,
    "ERR_EXCEPTION_AGREEMENT_NOT_FOUND": 404,
    "ERR_SHIPMENT_NOT_FOUND": 404,
    "ERR_SHIPMENT_LINE_NOT_FOUND": 404,
    "ERR_CAPTURE_EVENT_NOT_FOUND": 404,
    "ERR_INSPECTION_FINDING_NOT_FOUND": 404,
    "ERR_CORRECTION_NOTICE_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_CREDIT_MEMO_NOT_FOUND": 404,
    "ERR_REPRICING_RUN_NOT_FOUND": 404,
    # domain-typed shape
    "ERR_INVALID_CLASS_CODE": 422,
    "ERR_INVALID_DIMENSIONS": 422,
    "ERR_INVALID_DENSITY_BREAKS": 422,
    "ERR_INVALID_INTERVAL": 422,
    # optimistic concurrency
    "ERR_STALE_CUSTOMER_VERSION": 412,
    "ERR_STALE_SHIPMENT_VERSION": 412,
    # state
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_NOTICE_NOT_DISPUTABLE": 409,
    "ERR_SHIPMENT_NOT_BILLED": 409,
    "ERR_SHIPMENT_ALREADY_BILLED": 409,
    "ERR_OPEN_NOTICE_EXISTS": 409,
    # cross-entity state
    "ERR_DEVICE_OUT_OF_CALIBRATION": 409,
    "ERR_CUSTOMER_CREDIT_HOLD": 409,
    "ERR_CUSTOMER_CLOSED": 409,
    "ERR_EDUCATION_HOLD": 409,
    "ERR_TARIFF_NOT_PUBLISHED": 409,
    # safety / evidence
    "ERR_SOD_VIOLATION": 403,
    "ERR_INSUFFICIENT_EVIDENCE": 422,
    # temporal
    "ERR_DISPUTE_WINDOW_CLOSED": 409,
    "ERR_TARIFF_EFFECTIVE_CONFLICT": 409,
    # constraint
    "ERR_DUPLICATE_PRO_NUMBER": 409,
    "ERR_DUPLICATE_LINE_NO": 409,
    "ERR_EXCEPTION_OVERLAP": 409,
    "ERR_REPRICING_WINDOW_OVERLAP": 409,
    "ERR_MAX_DISPUTE_ROUNDS": 409,
    # referential
    "ERR_LINE_NO_MISMATCH": 422,
    "ERR_TARIFF_MISMATCH": 422,
    "ERR_NO_RECLASS_BASIS": 422,
    "ERR_INVALID_PARTIAL_OUTCOME": 422,
    # fiscal
    "ERR_NO_ACTIVE_RATE_PROGRAM": 422,
    "ERR_NO_EFFECTIVE_TARIFF": 422,
    "ERR_ZERO_DELTA_NOTICE": 422,
    "ERR_NO_SHIPMENT_LINES": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)
