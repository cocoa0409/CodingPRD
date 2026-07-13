"""Error catalogue (PRD section 5 / SCAFFOLD 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


HTTP_STATUS = {
    "ERR_INVALID_REQUEST": 400,
    "ERR_UNAUTHENTICATED": 401,
    "ERR_PROJECT_BUDGET_EXCEEDED": 402,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_BUILDING_NOT_FOUND": 404,
    "ERR_SPACE_NOT_FOUND": 404,
    "ERR_ASSET_NOT_FOUND": 404,
    "ERR_PM_PLAN_NOT_FOUND": 404,
    "ERR_VENDOR_NOT_FOUND": 404,
    "ERR_WORK_ORDER_NOT_FOUND": 404,
    "ERR_DISPATCH_NOT_FOUND": 404,
    "ERR_SHIFT_NOT_FOUND": 404,
    "ERR_LEASE_NOT_FOUND": 404,
    "ERR_ALLOCATION_NOT_FOUND": 404,
    "ERR_STATEMENT_NOT_FOUND": 404,
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_WORK_ORDER_NOT_OPEN": 409,
    "ERR_DISPATCH_NOT_ACTIONABLE": 409,
    "ERR_SHIFT_NOT_SCHEDULED": 409,
    "ERR_STATEMENT_NOT_ACTIONABLE": 409,
    "ERR_LEASE_NOT_DRAFT": 409,
    "ERR_LEASE_NOT_ACTIVE": 409,
    "ERR_PROJECT_NOT_PROPOSED": 409,
    "ERR_PROJECT_NOT_FUNDABLE": 409,
    "ERR_ASSET_NOT_IN_SERVICE": 409,
    "ERR_ASSET_RETIRED": 409,
    "ERR_BUILDING_FROZEN": 409,
    "ERR_BUILDING_RESTRICTED": 409,
    "ERR_VENDOR_SUSPENDED": 409,
    "ERR_SHIFT_OVERLAP": 409,
    "ERR_STATEMENT_PERIOD_DUPLICATE": 409,
    "ERR_DUPLICATE_BUILDING_CODE": 409,
    "ERR_DUPLICATE_ASSET_TAG": 409,
    "ERR_DUPLICATE_SPACE_CODE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_VENDOR_TRADE_MISMATCH": 422,
    "ERR_PM_PLAN_ASSET_MISMATCH": 422,
    "ERR_ASSET_BUILDING_MISMATCH": 422,
    "ERR_SPACE_BUILDING_MISMATCH": 422,
    "ERR_STATEMENT_PERIOD_INVALID": 422,
    "ERR_SPACE_SHARE_EXCEEDED": 422,
}

DEFAULT_MESSAGES = {
    "ERR_INVALID_REQUEST": "The request payload or query is invalid.",
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or the role is unknown.",
    "ERR_FORBIDDEN_ROLE": "The caller's role is not authorised for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The caller does not own this resource.",
    "ERR_SEGREGATION_OF_DUTIES": "The decider of a capital project must not be its proposer.",
    "ERR_STALE_VERSION": "The supplied version does not match the current version.",
    "ERR_PROJECT_BUDGET_EXCEEDED": "The capital project cannot cover this work order's estimate.",
}


def fail(error_id, message=None):
    raise ApiError(error_id, HTTP_STATUS[error_id], message)
