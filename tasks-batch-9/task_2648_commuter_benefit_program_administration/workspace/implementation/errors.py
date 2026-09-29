"""Error catalogue and the ApiError exception carried through the request ladder."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# ---------------------------------------------------------------- error catalog
ERROR_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_EMPLOYEE_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # path / body existence
    "ERR_EMPLOYER_NOT_FOUND": 404,
    "ERR_BENEFIT_CATEGORY_NOT_FOUND": 404,
    "ERR_EMPLOYEE_NOT_FOUND": 404,
    "ERR_ELECTION_WINDOW_NOT_FOUND": 404,
    "ERR_BENEFIT_ACCOUNT_NOT_FOUND": 404,
    "ERR_ELECTION_NOT_FOUND": 404,
    "ERR_TRANSIT_MEDIA_NOT_FOUND": 404,
    "ERR_ORDER_BATCH_NOT_FOUND": 404,
    "ERR_MEDIA_ORDER_NOT_FOUND": 404,
    "ERR_CARD_TRANSACTION_NOT_FOUND": 404,
    "ERR_SUBSTANTIATION_CLAIM_NOT_FOUND": 404,
    "ERR_PAYROLL_FILE_NOT_FOUND": 404,
    "ERR_LEDGER_ENTRY_NOT_FOUND": 404,
    "ERR_COMPLIANCE_ASSESSMENT_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_ENUM_VALUE": 422,
    "ERR_INVALID_PAGINATION": 422,
    # state / lifecycle
    "ERR_EMPLOYER_PROGRAM_NOT_ACTIVE": 409,
    "ERR_ELECTION_WINDOW_NOT_OPEN": 409,
    "ERR_ORDER_BATCH_NOT_OPEN": 409,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_ELECTION_ALREADY_FUNDED": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_ELECTION_WINDOW_OVERLAP": 409,
    "ERR_MEDIA_COVERAGE_OVERLAP": 409,
    "ERR_STALE_ACCOUNT_VERSION": 412,
    "ERR_STALE_ELECTION_VERSION": 412,
    # business rules
    "ERR_ORDINANCE_MANDATE_UNMET": 422,
    "ERR_SUBSTANTIATION_HOLD_ACTIVE": 422,
    "ERR_BENEFIT_CATEGORY_RETIRED": 422,
    "ERR_MEDIA_REGION_INELIGIBLE": 422,
    "ERR_TRANSIT_MEDIA_DISCONTINUED": 422,
    "ERR_ACCOUNT_MISMATCH": 422,
    "ERR_ALLOCATION_TYPE_NOT_ALLOWED": 422,
    "ERR_ORDER_CUTOFF_PASSED": 422,
    "ERR_MID_MONTH_CHANGE_NOT_ALLOWED": 422,
    "ERR_CHANGE_LIMIT_EXCEEDED": 422,
    "ERR_EMPTY_ORDER_BATCH": 422,
    "ERR_REISSUE_LIMIT_EXCEEDED": 422,
    "ERR_REPLACEMENT_FEE_NOT_WAIVABLE": 422,
    "ERR_REOPEN_LIMIT_EXCEEDED": 422,
    "ERR_EXCLUSION_LIMIT_EXCEEDED": 422,
    "ERR_INSUFFICIENT_BENEFIT_BALANCE": 402,
    "ERR_CLAIM_AMOUNT_MISMATCH": 422,
}


def fail(error_id, message):
    """Raise the catalogued error with its pinned HTTP status."""
    raise ApiError(error_id, ERROR_STATUS.get(error_id, 422), message)


def invalid_request(message):
    raise ApiError("ERR_INVALID_REQUEST", 422, message)


def invalid_enum(message):
    raise ApiError("ERR_INVALID_ENUM_VALUE", 422, message)


def invalid_pagination(message):
    raise ApiError("ERR_INVALID_PAGINATION", 422, message)


def bad_state(message):
    raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, message)


def already_terminal(message):
    raise ApiError("ERR_ALREADY_TERMINAL", 409, message)
