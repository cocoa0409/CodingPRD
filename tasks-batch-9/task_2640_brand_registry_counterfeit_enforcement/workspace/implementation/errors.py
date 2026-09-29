"""Error catalogue for the Brand Registry & Counterfeit Enforcement API."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


# error_id -> http status
CATALOGUE = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_BRAND_NOT_FOUND": 404,
    "ERR_REGISTRATION_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_REPRESENTATIVE_NOT_FOUND": 404,
    "ERR_SELLER_NOT_FOUND": 404,
    "ERR_LISTING_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_TEST_BUY_NOT_FOUND": 404,
    "ERR_EVIDENCE_PACKAGE_NOT_FOUND": 404,
    "ERR_TAKEDOWN_NOT_FOUND": 404,
    "ERR_COUNTER_NOTICE_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_CUSTOMS_RECORDATION_NOT_FOUND": 404,
    "ERR_INVESTIGATION_NOT_FOUND": 404,
    "ERR_STALE_BRAND_VERSION": 412,
    "ERR_STALE_CLAIM_VERSION": 412,
    "ERR_STALE_SELLER_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_ENROLLMENT_NOT_ACTIVE": 409,
    "ERR_LISTING_NOT_FLAGGED": 409,
    "ERR_EVIDENCE_PACKAGE_SEALED": 409,
    "ERR_REPRESENTATIVE_NOT_EFFECTIVE": 409,
    "ERR_REPRESENTATIVE_SCOPE_INSUFFICIENT": 403,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_SELLER_NOT_UNDER_INVESTIGATION": 422,
    "ERR_CEASE_DESIST_NOT_ANSWERED": 409,
    "ERR_REGISTRATION_NOT_ELIGIBLE": 422,
    "ERR_RECORDATION_NOT_PRINCIPAL_REGISTER": 422,
    "ERR_CHAIN_OF_CUSTODY_INCOMPLETE": 422,
    "ERR_EVIDENCE_INCOMPLETE": 422,
    "ERR_CLAIM_NOT_SUBSTANTIATED": 422,
    "ERR_COUNTER_NOTICE_WINDOW_EXPIRED": 422,
    "ERR_SEIZURE_RESPONSE_WINDOW_EXPIRED": 422,
    "ERR_DECISION_WINDOW_OPEN": 409,
    "ERR_LOT_CODE_NOT_TRACEABLE": 422,
    "ERR_EVIDENCE_PACKAGE_MISMATCH": 422,
    "ERR_ALIAS_CHAIN_NOT_ALLOWED": 422,
    "ERR_DUPLICATE_COUNTER_NOTICE": 409,
    "ERR_DUPLICATE_ENROLLMENT": 409,
    "ERR_MAX_TAKEDOWN_ROUNDS": 409,
    "ERR_REPRESENTATIVE_WINDOW_OVERLAP": 409,
    "ERR_TEST_BUY_COOLING_PERIOD": 409,
    "ERR_RECORDATION_WINDOW_OVERLAP": 409,
    "ERR_TEST_BUY_BUDGET_EXCEEDED": 402,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or name an unknown role.",
    "ERR_UNAUTHORIZED": "The authenticated role may not perform this operation.",
    "ERR_INVALID_REQUEST": "The request payload is malformed or violates a field constraint.",
    "ERR_INVALID_PAGINATION": "Pagination parameters are outside the permitted range.",
    "ERR_INVALID_STATE": "The target row is not in a state from which this transition exists.",
}


def fail(error_id, message=None):
    raise ApiError(error_id, CATALOGUE[error_id], message)
