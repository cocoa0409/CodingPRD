"""Error classes and the error catalog (PRD §5 / SCAFFOLD §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Catalog: error_id -> http status (PRD §5)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_DUPLICATE_EMAIL = "ERR_DUPLICATE_EMAIL"
ERR_COMMISSION_WITHOUT_AGENT = "ERR_COMMISSION_WITHOUT_AGENT"
ERR_TIER_COVERAGE_INVALID = "ERR_TIER_COVERAGE_INVALID"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_CROSS_CONTRACT_REFERENCE = "ERR_CROSS_CONTRACT_REFERENCE"
ERR_PERIOD_NOT_OPEN = "ERR_PERIOD_NOT_OPEN"
ERR_PERIOD_SEQUENCE_VIOLATION = "ERR_PERIOD_SEQUENCE_VIOLATION"
ERR_STATEMENT_EXISTS = "ERR_STATEMENT_EXISTS"
ERR_RIGHT_ALREADY_SETTLED = "ERR_RIGHT_ALREADY_SETTLED"
ERR_OPEN_LIABILITIES = "ERR_OPEN_LIABILITIES"
ERR_STALE_CONTRACT_VERSION = "ERR_STALE_CONTRACT_VERSION"
ERR_DUPLICATE_PERIOD_SEQUENCE = "ERR_DUPLICATE_PERIOD_SEQUENCE"
ERR_VALIDATION_RANGE = "ERR_VALIDATION_RANGE"
ERR_TITLE_HAS_NO_FORMAT = "ERR_TITLE_HAS_NO_FORMAT"
ERR_CONTRACT_NOT_READY = "ERR_CONTRACT_NOT_READY"


def unauthenticated(msg="Missing or invalid authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="Role not permitted for this operation."):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def not_found(msg="Referenced resource does not exist."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Malformed or invalid request body."):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def validation_range(msg="A numeric input violates its declared range."):
    return ApiError(ERR_VALIDATION_RANGE, 422, msg)


def duplicate_email(msg="Email already exists."):
    return ApiError(ERR_DUPLICATE_EMAIL, 409, msg)


def commission_without_agent(msg="agent_commission_pct must be 0 when agent_id is null."):
    return ApiError(ERR_COMMISSION_WITHOUT_AGENT, 422, msg)


def tier_coverage_invalid(msg="Royalty tiers do not form a contiguous cover from 1 with one open top tier."):
    return ApiError(ERR_TIER_COVERAGE_INVALID, 422, msg)


def invalid_state(msg="Resource is not in a state that permits this transition."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def cross_contract_reference(msg="format_id belongs to a different contract than the period."):
    return ApiError(ERR_CROSS_CONTRACT_REFERENCE, 422, msg)


def period_not_open(msg="Period is not OPEN, format inactive, or contract not ACTIVE."):
    return ApiError(ERR_PERIOD_NOT_OPEN, 409, msg)


def period_sequence_violation(msg="An earlier-sequence period is not yet STATEMENTED."):
    return ApiError(ERR_PERIOD_SEQUENCE_VIOLATION, 409, msg)


def statement_exists(msg="A statement already exists for this period."):
    return ApiError(ERR_STATEMENT_EXISTS, 409, msg)


def right_already_settled(msg="Cannot void a STATEMENTED or VOID subsidiary right."):
    return ApiError(ERR_RIGHT_ALREADY_SETTLED, 409, msg)


def open_liabilities(msg="Contract has held reserves or unpaid statements."):
    return ApiError(ERR_OPEN_LIABILITIES, 409, msg)


def stale_contract_version(msg="expected_contract_version does not match live contract version."):
    return ApiError(ERR_STALE_CONTRACT_VERSION, 412, msg)


def duplicate_period_sequence(msg="A sales period with this sequence already exists on the contract."):
    return ApiError(ERR_DUPLICATE_PERIOD_SEQUENCE, 409, msg)


def title_has_no_format(msg="Cannot publish a title with zero formats."):
    return ApiError(ERR_TITLE_HAS_NO_FORMAT, 409, msg)


def contract_not_ready(msg="Contract lacks tiers, a title, or a format."):
    return ApiError(ERR_CONTRACT_NOT_READY, 409, msg)
