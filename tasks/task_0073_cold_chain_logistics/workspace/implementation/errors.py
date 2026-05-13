"""Error definitions for the cold-chain-logistics API."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Status -> error_id mapping for quick reference
ERROR_CATALOG = {
    "ERR_AUTH_MISSING": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_SEGREGATION_VIOLATION": 403,
    "ERR_TASK_NOT_RESOLVABLE": 409,
    "ERR_DECISION_NOT_FINALIZED": 409,
    "ERR_EVIDENCE_REQUIRED": 422,
    "ERR_INVOICE_VALUE_REQUIRED": 422,
    "ERR_VEHICLE_OVERLAP": 409,
    "ERR_DRIVER_HOURS_EXCEEDED": 409,
    "ERR_READING_OUT_OF_WINDOW": 422,
    "ERR_PCT_SUM_INVALID": 422,
    "ERR_INSURANCE_CAP_EXCEEDED": 422,
    "ERR_QUANTITY_INVALID": 422,
    "ERR_AMOUNT_INVALID": 422,
    "ERR_VALIDATION": 422,
    "ERR_HANDOVER_ALREADY_EXISTS": 409,
}


def err(error_id: str, message: str = ""):
    """Helper that raises an APIError with the proper HTTP status."""
    raise APIError(error_id, ERROR_CATALOG[error_id], message or error_id)
