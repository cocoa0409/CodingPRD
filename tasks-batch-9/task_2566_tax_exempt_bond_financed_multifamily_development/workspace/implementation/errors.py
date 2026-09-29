"""Error catalogue (PRD section 5) and the ApiError exception."""


# error_id -> HTTP status code
ERROR_CATALOG = {
    # auth / identity
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # input
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_DEVELOPER_NOT_FOUND": 404,
    "ERR_INVESTOR_NOT_FOUND": 404,
    "ERR_CAP_POOL_NOT_FOUND": 404,
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_ALLOCATION_NOT_FOUND": 404,
    "ERR_BOND_ISSUE_NOT_FOUND": 404,
    "ERR_DRAW_REQUEST_NOT_FOUND": 404,
    "ERR_UNIT_RESTRICTION_NOT_FOUND": 404,
    "ERR_REG_AGREEMENT_NOT_FOUND": 404,
    "ERR_COST_CERT_NOT_FOUND": 404,
    "ERR_CREDIT_ALLOCATION_NOT_FOUND": 404,
    "ERR_DELIVERY_NOT_FOUND": 404,
    "ERR_COMPLIANCE_REPORT_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_CAP_POOL_VERSION": 412,
    "ERR_STALE_BOND_ISSUE_VERSION": 412,
    "ERR_STALE_CREDIT_ALLOCATION_VERSION": 412,
    # state
    "ERR_DEVELOPER_NOT_ACTIVE": 409,
    "ERR_ALLOCATION_STATE_INVALID": 409,
    "ERR_ALLOCATION_EXPIRED": 409,
    "ERR_BOND_ISSUE_STATE_INVALID": 409,
    "ERR_DRAW_STATE_INVALID": 409,
    "ERR_UNIT_RESTRICTION_STATE_INVALID": 409,
    "ERR_REG_AGREEMENT_STATE_INVALID": 409,
    "ERR_REG_AGREEMENT_NOT_RECORDED": 409,
    "ERR_COST_CERT_STATE_INVALID": 409,
    "ERR_COST_CERT_NOT_ACCEPTED": 409,
    "ERR_COST_CERT_PROJECT_MISMATCH": 409,
    "ERR_PROJECT_NOT_PLACED_IN_SERVICE": 409,
    "ERR_CREDIT_ALLOCATION_STATE_INVALID": 409,
    "ERR_DELIVERY_STATE_INVALID": 409,
    "ERR_COMPLIANCE_REPORT_STATE_INVALID": 409,
    "ERR_INSPECTION_STATE_INVALID": 409,
    # business - temporal
    "ERR_DRAW_PERIOD_OVERLAP": 409,
    "ERR_INSPECTION_WINDOW_CONFLICT": 409,
    "ERR_INSPECTION_OUTSIDE_COMPLIANCE_PERIOD": 422,
    "ERR_DUPLICATE_COMPLIANCE_REPORT": 409,
    # business - fiscal
    "ERR_INSUFFICIENT_VOLUME_CAP": 422,
    "ERR_PAR_EXCEEDS_CAP_AWARD": 422,
    "ERR_DRAW_EXCEEDS_UNDRAWN": 422,
    "ERR_NEGATIVE_ARBITRAGE_ALLOWANCE_EXCEEDED": 422,
    "ERR_FIFTY_PERCENT_TEST_FAILED": 422,
    "ERR_INSUFFICIENT_OPERATING_HISTORY": 422,
    "ERR_DSCR_BELOW_MINIMUM": 422,
    "ERR_OCCUPANCY_BELOW_STABILIZATION": 422,
    "ERR_NO_UNDELIVERED_CREDIT": 422,
    # business - safety
    "ERR_SET_ASIDE_NOT_SATISFIED": 422,
    "ERR_UNIT_COUNT_MISMATCH": 422,
    # business - constraint
    "ERR_SET_ASIDE_MISMATCH": 422,
    "ERR_EXTENDED_USE_TOO_SHORT": 422,
    "ERR_DUPLICATE_UNIT_NUMBER": 409,
    "ERR_UNIT_COUNT_EXCEEDS_TOTAL": 422,
    "ERR_AMI_PERCENT_NOT_ALLOWED": 422,
    "ERR_DUPLICATE_OPERATING_MONTH": 409,
    "ERR_ALLOCATION_ALREADY_EXISTS": 409,
    "ERR_REPORT_COUNTS_INCOHERENT": 422,
    # fallback for unrouted requests
    "ERR_NOT_FOUND": 404,
}


class ApiError(Exception):
    """Raised anywhere in a handler to abort with a catalogued error."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_CATALOG.get(error_id, 400)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return "Request rejected: %s." % words


def fail(error_id, message=None):
    raise ApiError(error_id, message)
