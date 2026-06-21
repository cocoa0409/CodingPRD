"""Error catalog and ApiError exception for the Vocational/Trade School API."""


class ApiError(Exception):
    """Carries an error_id, human message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status per error id (from PRD §5 / SCAFFOLD §1.6)
ERROR_HTTP = {
    "ERR_MISSING_AUTH_HEADER": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_KEY": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_PROGRAM_NOT_OPEN": 409,
    "ERR_COHORT_NOT_STARTED": 409,
    "ERR_COHORT_CLOSED": 409,
    "ERR_COHORT_FULL": 409,
    "ERR_OPEN_AGREEMENTS_EXIST": 409,
    "ERR_ADMISSION_PREREQ_UNMET": 422,
    "ERR_SCOPE_MISMATCH": 409,
    "ERR_SAP_DISMISSED": 409,
    "ERR_SAP_NOT_SATISFACTORY": 422,
    "ERR_SAP_NOT_APPEALABLE": 409,
    "ERR_AGREEMENT_NOT_ACTIVE": 409,
    "ERR_CLOCK_HOURS_UNMET": 422,
    "ERR_THEORY_HOURS_UNMET": 422,
    "ERR_EXTERNSHIP_HOURS_UNMET": 422,
    "ERR_BALANCE_OUTSTANDING": 402,
    "ERR_DISBURSEMENT_GATE_UNMET": 422,
    "ERR_DISBURSEMENT_OUT_OF_ORDER": 409,
    "ERR_AID_OVER_AWARD": 402,
    "ERR_AGREEMENT_NOT_WITHDRAWN": 409,
    "ERR_REFUND_ALREADY_SETTLED": 409,
    "ERR_SITE_SUSPENDED": 409,
    "ERR_EXTERNSHIP_WINDOW_CONFLICT": 409,
    "ERR_SITE_CAPACITY_EXCEEDED": 409,
    "ERR_EXTERNSHIP_NOT_STARTED": 409,
}


def err(error_id, message=None):
    """Build an ApiError using the catalog's HTTP status."""
    return ApiError(error_id, ERROR_HTTP.get(error_id, 400), message)
