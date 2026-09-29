"""Error catalogue and the ApiError exception (PRD section 5)."""

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_MEMBER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_CONTRACT_ITEM_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_COMMITMENT_NOT_FOUND": 404,
    "ERR_XREF_NOT_FOUND": 404,
    "ERR_ACTIVATION_NOT_FOUND": 404,
    "ERR_FILE_NOT_FOUND": 404,
    "ERR_MEASUREMENT_NOT_FOUND": 404,
    "ERR_DISTRIBUTION_NOT_FOUND": 404,
    "ERR_REVIEW_NOT_FOUND": 404,
    "ERR_PURCHASE_LINE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_TIER_LADDER": 400,
    "ERR_INVALID_HOLDBACK_LADDER": 400,
    "ERR_CONTRACT_NOT_ACTIVE": 409,
    "ERR_MEMBER_NOT_ACTIVE": 409,
    "ERR_CONTRACT_ITEM_NOT_ACTIVE": 409,
    "ERR_INVALID_REVIEW_STATE": 409,
    "ERR_XREF_NOT_PROPOSED": 409,
    "ERR_COMMITMENT_NOT_ELECTED": 409,
    "ERR_COMMITMENT_NOT_ACTIVE": 409,
    "ERR_INVALID_LOP_STATE": 409,
    "ERR_INVALID_ACTIVATION_STATE": 409,
    "ERR_INVALID_FILE_STATE": 409,
    "ERR_INVALID_MEASUREMENT_STATE": 409,
    "ERR_INVALID_DISTRIBUTION_STATE": 409,
    "ERR_STALE_COMMITMENT_VERSION": 412,
    "ERR_STALE_CONTRACT_VERSION": 412,
    "ERR_CLINICAL_REVIEW_NOT_ENDORSED": 409,
    "ERR_EVIDENCE_SCORE_BELOW_THRESHOLD": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    "ERR_ITEM_CONTRACT_MISMATCH": 409,
    "ERR_MEMBER_ITEM_NOT_IN_MASTER": 409,
    "ERR_XREF_NOT_APPROVED": 409,
    "ERR_COMMITMENT_NOT_IN_REQUAL_REVIEW": 409,
    "ERR_REQUALIFICATION_IN_PROGRESS": 409,
    "ERR_DUPLICATE_COMMITMENT": 409,
    "ERR_DUPLICATE_XREF": 409,
    "ERR_DUPLICATE_MEASUREMENT_PERIOD": 409,
    "ERR_DUPLICATE_DISTRIBUTION_PERIOD": 409,
    "ERR_DUPLICATE_TIER_CODE": 409,
    "ERR_TIER_CODE_UNKNOWN": 409,
    "ERR_EFFECTIVE_WINDOW_INVALID": 409,
    "ERR_PERIOD_OUTSIDE_CONTRACT_TERM": 409,
    "ERR_FILE_PERIOD_OVERLAP": 409,
    "ERR_ACTIVATION_PERIOD_OVERLAP": 409,
    "ERR_REQUESTED_PRICE_REQUIRED": 409,
    "ERR_REQUESTED_PRICE_NOT_ALLOWED": 409,
    "ERR_COMMITTED_VOLUME_BELOW_TIER": 409,
    "ERR_BASE_PRICE_BELOW_FLOOR": 409,
    "ERR_COLLECTION_EXCEEDS_ACCRUAL": 409,
    "ERR_DISTRIBUTION_BASIS_MISMATCH": 409,
    "ERR_DISTRIBUTION_BASIS_NOT_COLLECTABLE": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication is required: X-User-ID must be present and non-empty.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not permitted to perform this operation.",
    "ERR_MEMBER_SCOPE_VIOLATION": "The acting member may only operate on its own records.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids the same user performing both steps.",
    "ERR_INVALID_REQUEST": "The request body or query string is invalid.",
}


class ApiError(Exception):
    """An error carrying the catalogue error_id, message and HTTP status."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        super().__init__(self.message)


def api_error(error_id, message=None):
    return ApiError(error_id, message)
