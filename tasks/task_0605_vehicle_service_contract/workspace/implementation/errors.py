"""Error class and the complete error catalog (Table 1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Catalog: error_id -> http status
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_PLAN_IN_USE": 409,
    "ERR_PLAN_NOT_ACTIVE": 409,
    "ERR_INVALID_CESSION_PCT": 422,
    "ERR_VEHICLE_INELIGIBLE": 422,
    "ERR_FINANCE_TERM_REQUIRED": 422,
    "ERR_CONTRACT_NOT_ACTIVE": 409,
    "ERR_MILEAGE_EXCEEDED": 422,
    "ERR_OPEN_CLAIM_BLOCKS": 409,
    "ERR_NOTHING_COVERED": 422,
    "ERR_INVALID_CLAIM_LINE": 422,
    "ERR_CLAIM_NOT_APPROVED": 409,
    "ERR_CLAIM_NOT_AUTHORIZED": 409,
    "ERR_FACILITY_NOT_DIRECT_PAY": 422,
    "ERR_STALE_CONTRACT_VERSION": 412,
    "ERR_BUNDLE_TOO_LATE": 422,
    "ERR_CLAIM_IN_FLIGHT": 409,
    "ERR_CANCELLATION_NOT_APPROVED": 409,
    "ERR_CONTRACT_NOT_CANCELLABLE": 409,
    "ERR_VALIDATION_RANGE": 422,
    "ERR_PAGINATION_INVALID": 422,
    "ERR_CLOCK_INVALID": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
