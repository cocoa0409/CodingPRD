"""Error catalog and the ApiError exception.

Every error_id and HTTP status traces to PRD §5 (Error Code Catalogue) and the
SCAFFOLD errors table.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id -> http_status (PRD §5)
ERROR_STATUS = {
    "ERR_MISSING_USER_CONTEXT": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_DUPLICATE_ASSET_TAG": 409,
    "ERR_DUPLICATE_CERTIFICATE_NUMBER": 409,
    "ERR_TRACEABILITY_CYCLE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_INSTRUMENT_NOT_ACTIVE": 409,
    "ERR_INSTRUMENT_RETIRED": 409,
    "ERR_STANDARD_NOT_TRACEABLE": 409,
    "ERR_VENDOR_NOT_ELIGIBLE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NO_MEASUREMENT_POINTS": 409,
    "ERR_INCOMPLETE_TRIAL_MATRIX": 409,
    "ERR_NO_RECALLABLE_PRODUCT": 409,
    "ERR_OPEN_IMPACT_EXISTS": 409,
    "ERR_LATEST_CAL_NOT_PASSING": 409,
    "ERR_OPEN_CALIBRATION_EXISTS": 409,
    "ERR_DUPLICATE_TRIAL_CELL": 409,
    "ERR_GAGE_RR_UNACCEPTABLE": 409,
    "ERR_IMPACT_NOT_CANCELLED": 409,
    "ERR_RECALL_ALREADY_ISSUED": 409,
    "ERR_CERT_VENDOR_MISMATCH": 409,
    "ERR_EVENT_NOT_FINALIZED": 409,
    "ERR_STALE_INSTRUMENT_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
