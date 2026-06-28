"""Error catalogue (§5 / §1.6). Custom exception carrying error_id, message, http_status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error ID -> HTTP status (PRD §5 Error Code Catalogue)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_FUND_VERSION": 412,
    "ERR_STALE_HOLDING_VERSION": 412,
    "ERR_OFFERING_NOT_OPEN": 409,
    "ERR_SUITABILITY_NOT_APPROVED": 409,
    "ERR_ACCREDITATION_REQUIRED": 409,
    "ERR_BELOW_MIN_INVESTMENT": 422,
    "ERR_INSUFFICIENT_SHARES": 422,
    "ERR_FUND_WINDING_DOWN": 409,
    "ERR_NO_VALUATION": 409,
    "ERR_DUPLICATE": 409,
    "ERR_ANNUAL_CAP_EXCEEDED": 409,
    "ERR_REDEMPTION_CAP_REACHED": 409,
    "ERR_INVALID_REQUEST": 400,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
