"""Error identifiers and the ApiError exception carried through the stack."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_UNKNOWN_ACTOR": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_BREWER_NOT_FOUND": 404,
    "ERR_DISTRIBUTOR_NOT_FOUND": 404,
    "ERR_POOL_NOT_FOUND": 404,
    "ERR_KEG_NOT_FOUND": 404,
    "ERR_SCAN_EVENT_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_SERVICE_CENTER_NOT_FOUND": 404,
    "ERR_SERVICE_CYCLE_NOT_FOUND": 404,
    "ERR_ASSESSMENT_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_ACCRUAL_NOT_FOUND": 404,
    "ERR_INVESTIGATION_NOT_FOUND": 404,
    "ERR_STALE_AGREEMENT_VERSION": 412,
    "ERR_STALE_KEG_VERSION": 412,
    "ERR_STALE_CLAIM_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_AGREEMENT_NOT_ACTIVE": 409,
    "ERR_POOL_FROZEN": 409,
    "ERR_POOL_RESTRICTED": 409,
    "ERR_FLOAT_SUSPENDED": 409,
    "ERR_BREWER_SUSPENDED": 409,
    "ERR_DISTRIBUTOR_SUSPENDED": 409,
    "ERR_SCAN_SEQUENCE_INVALID": 409,
    "ERR_RESPONDER_OUT_OF_TURN": 409,
    "ERR_QUARANTINE_RELEASE_BLOCKED": 409,
    "ERR_DUPLICATE_SCAN": 409,
    "ERR_CUSTODY_INTERVAL_CONFLICT": 409,
    "ERR_INTAKE_WINDOW_CONFLICT": 409,
    "ERR_DUPLICATE_BRAND_CODE": 409,
    "ERR_DUPLICATE_POOL_CODE": 409,
    "ERR_DUPLICATE_ASSET_TAG": 409,
    "ERR_DUPLICATE_INDEX_DATE": 409,
    "ERR_AGREEMENT_ALREADY_ACTIVE": 409,
    "ERR_ASSESSMENT_ALREADY_OPEN": 409,
    "ERR_CLAIM_ALREADY_OPEN": 409,
    "ERR_CLAIM_ROUND_LIMIT": 409,
    "ERR_SERVICE_CAPACITY_EXCEEDED": 409,
    "ERR_NO_ELIGIBLE_KEGS": 409,
    "ERR_INSUFFICIENT_FLOAT": 409,
    "ERR_AGREEMENT_FLOAT_OUTSTANDING": 409,
    "ERR_KEG_NOT_ATTACHED": 409,
    "ERR_ACCRUAL_NOT_PAYABLE": 409,
    "ERR_KEG_NOT_FIT_FOR_FILL": 422,
    "ERR_PRESSURE_TEST_OVERDUE": 422,
    "ERR_CAUSTIC_CYCLE_TOO_SHORT": 422,
    "ERR_PRESSURE_TEST_PSI_TOO_LOW": 422,
    "ERR_BRAND_MISMATCH": 422,
    "ERR_SCAN_PARTY_MISMATCH": 422,
    "ERR_BRAND_OWNER_UNKNOWN": 422,
    "ERR_NO_MISDELIVERY_EVIDENCE": 422,
    "ERR_CLAIM_SUPERSEDE_MISMATCH": 422,
    "ERR_NO_CHARGEABLE_PARTY": 422,
    "ERR_NO_COMMODITY_INDEX": 422,
    "ERR_SCAN_TIMESTAMP_FUTURE": 422,
    "ERR_CLAIM_WINDOW_EXPIRED": 422,
    "ERR_FLOAT_SIZE_EXCEEDED": 422,
    "ERR_SETTLEMENT_AMOUNT_MISMATCH": 422,
    "ERR_CREDIT_LIMIT_EXCEEDED": 402,
}

_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and a valid X-User-Role header are required.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorised for this operation.",
    "ERR_UNKNOWN_ACTOR": "The acting identifier does not name an existing row of its entity.",
    "ERR_NOT_RESOURCE_OWNER": "The acting principal does not own the target resource.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this actor from this action.",
    "ERR_INVALID_REQUEST": "The request body or query is malformed.",
    "ERR_INVALID_PAGINATION": "limit must be an integer 1..100 and offset an integer >= 0.",
}


def fail(error_id, message=None):
    raise ApiError(error_id, HTTP[error_id], message)
