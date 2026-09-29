"""Error catalog: every error_id declared by the PRD with its HTTP status."""

ERROR_HTTP = {
    # auth / access
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_OWNERSHIP_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # existence
    "ERR_MOVE_NOT_FOUND": 404,
    "ERR_RESIDENT_NOT_FOUND": 404,
    "ERR_UTILITY_ORDER_NOT_FOUND": 404,
    "ERR_HANDOFF_NOT_FOUND": 404,
    "ERR_FILING_NOT_FOUND": 404,
    "ERR_PLACEMENT_NOT_FOUND": 404,
    "ERR_CONSENT_NOT_FOUND": 404,
    "ERR_VERIFICATION_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    # shape
    "ERR_INVALID_REQUEST": 422,
    # state
    "ERR_MOVE_NOT_ACTIONABLE": 409,
    "ERR_ORDER_NOT_SCHEDULABLE": 409,
    "ERR_FILING_NOT_SUBMITTABLE": 409,
    "ERR_PLACEMENT_NOT_CONVERTIBLE": 409,
    "ERR_CONSENT_ALREADY_TERMINAL": 409,
    "ERR_VERIFICATION_ALREADY_DECIDED": 409,
    "ERR_HANDOFF_NOT_OPEN": 409,
    # concurrency
    "ERR_STALE_RESIDENT_VERSION": 412,
    "ERR_STALE_MOVE_VERSION": 412,
    # identity
    "ERR_IDENTITY_NOT_VERIFIED": 422,
    "ERR_IDENTITY_VERIFICATION_EXPIRED": 422,
    "ERR_VERIFICATION_ATTEMPTS_EXHAUSTED": 409,
    # consent
    "ERR_CONSENT_MISSING": 422,
    "ERR_CONSENT_REVOKED": 409,
    "ERR_MARKETING_OPT_OUT": 422,
    # provider / coverage
    "ERR_NO_PROVIDER_COVERAGE": 422,
    "ERR_MISSING_ACCOUNT_DATA": 422,
    "ERR_PROVIDER_INACTIVE": 409,
    "ERR_FEED_SUSPENDED": 409,
    "ERR_TYPE_ALREADY_MAPPED": 409,
    "ERR_TERRITORY_OVERLAP": 409,
    # duplicates
    "ERR_DUPLICATE_MOVE_UNRESOLVED": 409,
    "ERR_SELF_MERGE_FORBIDDEN": 422,
    "ERR_SURVIVOR_MOVE_INVALID": 422,
    # scheduling
    "ERR_MOVE_DATE_OUT_OF_RANGE": 422,
    "ERR_INVALID_SERVICE_WINDOW": 422,
    "ERR_LEAD_TIME_VIOLATION": 422,
    "ERR_SERVICE_WINDOW_CONFLICT": 409,
    "ERR_ACTIVATION_TOO_EARLY": 409,
    "ERR_MOVE_DATE_NOT_REACHED": 409,
    "ERR_UNRESOLVED_PROVISION_FAILURE": 409,
    # credit / deposits
    "ERR_CREDIT_NOT_CLEARED": 409,
    "ERR_DEPOSIT_CAP_EXCEEDED": 422,
    "ERR_DEPOSIT_AMOUNT_MISMATCH": 422,
    "ERR_HANDOFF_ALREADY_OPEN": 409,
    # usps filing
    "ERR_ADDRESS_NOT_DELIVERABLE": 422,
    "ERR_FORWARD_DATE_INVALID": 422,
    "ERR_FORWARDING_PERIOD_CONFLICT": 409,
    "ERR_RESUBMIT_LIMIT_REACHED": 409,
    # referral
    "ERR_ATTRIBUTION_WINDOW_EXPIRED": 422,
    "ERR_DUPLICATE_VERTICAL_PLACEMENT": 409,
    "ERR_PARTNER_PAUSED": 409,
    "ERR_PARTNER_CAP_REACHED": 409,
    "ERR_SETTLEMENT_AMOUNT_INVALID": 422,
    # generic
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or invalid.",
    "ERR_FORBIDDEN_ROLE": "The caller's role may not perform this operation.",
    "ERR_OWNERSHIP_VIOLATION": "The caller does not own the addressed resource.",
    "ERR_INVALID_REQUEST": "The request body or query is malformed.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").lower().capitalize() + "."
        )
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
