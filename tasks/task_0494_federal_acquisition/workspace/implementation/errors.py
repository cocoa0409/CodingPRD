"""Error catalogue (PRD §5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error id -> HTTP status, exactly per the PRD §5 catalogue.
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_PROPOSAL_NOT_ELIGIBLE": 409,
    "ERR_SET_ASIDE_INELIGIBLE": 422,
    "ERR_REGISTRATION_NOT_ACTIVE": 422,
    "ERR_DEADLINE_PASSED": 422,
    "ERR_OPTION_WINDOW_CLOSED": 422,
    "ERR_FACTOR_WEIGHTS_INVALID": 422,
    "ERR_DUPLICATE_UEI": 409,
    "ERR_DUPLICATE_CLIN": 409,
    "ERR_INVOICE_SHAPE_MISMATCH": 422,
    "ERR_CLIN_OVERDELIVERY": 422,
    "ERR_CEILING_EXCEEDED": 422,
    "ERR_CEILING_REACHED_NO_OPTION": 422,
    "ERR_PROTESTER_NOT_OFFEROR": 422,
    "ERR_INVALID_REQUEST": 400,
    "ERR_VALIDATION": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
