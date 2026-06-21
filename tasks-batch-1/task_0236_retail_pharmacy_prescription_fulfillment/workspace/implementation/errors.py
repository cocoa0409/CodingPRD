"""Error catalog and the ApiError exception type."""


class ApiError(Exception):
    """Carries an error_id, human message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error ID -> HTTP status (PRD §5 / scaffold §1.6)
ERROR_STATUS = {
    "ERR_MISSING_USER_CONTEXT": 401,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_NDC": 409,
    "ERR_DUPLICATE_PLAN_ROUTING": 409,
    "ERR_DUPLICATE_NPI": 409,
    "ERR_STALE_PRESCRIPTION_VERSION": 412,
    "ERR_STALE_PA_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_PRESCRIPTION_NOT_ACTIVE": 409,
    "ERR_OPEN_FILL_EXISTS": 409,
    "ERR_FILL_NOT_ENTERED": 409,
    "ERR_FILL_NOT_IN_DUR_REVIEW": 409,
    "ERR_FILL_NOT_ADJUDICATING": 409,
    "ERR_FILL_NOT_READY": 409,
    "ERR_FILL_NOT_WILL_CALL": 409,
    "ERR_FILL_NOT_CANCELLABLE": 409,
    "ERR_FILL_ALREADY_DISPENSED": 409,
    "ERR_CLAIM_ALREADY_OPEN": 409,
    "ERR_CLAIM_NOT_PAID": 409,
    "ERR_CLAIM_PAID_REVERSE_FIRST": 409,
    "ERR_PA_NOT_PENDING": 409,
    "ERR_PA_EXPIRED": 409,
    "ERR_PATIENT_NOT_BLOCKED": 409,
    "ERR_PRESCRIBER_DEA_INVALID": 422,
    "ERR_DRUG_DISCONTINUED": 409,
    "ERR_DUR_NOT_OVERRIDDEN": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_PATIENT_CONTROLLED_LOCKED": 403,
    "ERR_OVERRIDE_REASON_REQUIRED": 422,
    "ERR_REFILL_TOO_SOON": 409,
    "ERR_WILL_CALL_EXPIRED": 409,
    "ERR_NO_REFILLS_REMAINING": 409,
    "ERR_DRUG_NOT_ON_FORMULARY": 422,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
    "ERR_PAYMENT_REQUIRED": 409,
}


def err(error_id, message=None):
    """Build an ApiError using the catalog's HTTP status for the id."""
    return ApiError(error_id, ERROR_STATUS[error_id], message)
