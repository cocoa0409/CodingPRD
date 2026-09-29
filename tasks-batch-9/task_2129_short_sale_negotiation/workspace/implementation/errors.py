"""Error catalogue (PRD §5 / SCAFFOLD §1.6)."""

ERROR_HTTP = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_ACTOR_NOT_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_PACKAGE_NOT_FOUND": 404,
    "ERR_DOCUMENT_NOT_FOUND": 404,
    "ERR_LISTING_NOT_FOUND": 404,
    "ERR_OFFER_NOT_FOUND": 404,
    "ERR_VALUATION_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_LIEN_NOT_FOUND": 404,
    "ERR_MI_CLAIM_NOT_FOUND": 404,
    "ERR_APPROVAL_NOT_FOUND": 404,
    "ERR_EXTENSION_NOT_FOUND": 404,
    "ERR_VENDOR_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_CASE_VERSION": 412,
    "ERR_STALE_OFFER_VERSION": 412,
    # uniqueness
    "ERR_DUPLICATE_RESOURCE": 409,
    # state preconditions
    "ERR_CASE_NOT_ACTIONABLE": 409,
    "ERR_PACKAGE_NOT_ACTIONABLE": 409,
    "ERR_DOCUMENT_NOT_REVIEWABLE": 409,
    "ERR_LISTING_NOT_ACTIONABLE": 409,
    "ERR_OFFER_NOT_ACTIONABLE": 409,
    "ERR_VALUATION_NOT_ACTIONABLE": 409,
    "ERR_DISPUTE_NOT_OPEN": 409,
    "ERR_LIEN_NOT_ACTIONABLE": 409,
    "ERR_MI_CLAIM_NOT_DECIDABLE": 409,
    "ERR_APPROVAL_NOT_ACTIVE": 409,
    "ERR_APPROVAL_EXPIRED": 409,
    "ERR_EXTENSION_NOT_PENDING": 409,
    "ERR_STALE_NET_SHEET": 409,
    # temporal / interval
    "ERR_LISTING_WINDOW_OVERLAP": 409,
    "ERR_VENDOR_SCHEDULE_CONFLICT": 409,
    "ERR_VENDOR_DAILY_CAPACITY_EXCEEDED": 422,
    # compliance / safety
    "ERR_REQUIRED_DOCUMENT_MISSING": 422,
    "ERR_DOCUMENT_EXPIRED": 422,
    "ERR_DEFICIENCY_WAIVER_NOT_PERMITTED": 422,
    # cross-entity readiness
    "ERR_CONTROLLING_VALUATION_MISSING": 422,
    "ERR_HARDSHIP_NOT_ACCEPTED": 422,
    "ERR_JUNIOR_LIEN_UNRESOLVED": 422,
    "ERR_MI_APPROVAL_PENDING": 422,
    # marketing / negotiation
    "ERR_MARKETING_PERIOD_NOT_MET": 422,
    "ERR_PRICE_REDUCTION_REQUIRED": 422,
    "ERR_NEGOTIATION_ROUNDS_EXHAUSTED": 422,
    "ERR_DISPUTE_VARIANCE_TOO_SMALL": 422,
    "ERR_DISPUTE_EVIDENCE_INSUFFICIENT": 422,
    # fiscal
    "ERR_HARDSHIP_SCORE_BELOW_MINIMUM": 422,
    "ERR_LIEN_CONTRIBUTION_EXCEEDS_CAP": 422,
    "ERR_COMMISSION_CAP_EXCEEDED": 422,
    "ERR_NET_BELOW_MINIMUM": 422,
    "ERR_EXTENSION_BUDGET_EXCEEDED": 422,
    # fallback for unrouted paths
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# not-found code by entity kind
NOT_FOUND = {
    "case": "ERR_CASE_NOT_FOUND",
    "package": "ERR_PACKAGE_NOT_FOUND",
    "document": "ERR_DOCUMENT_NOT_FOUND",
    "listing": "ERR_LISTING_NOT_FOUND",
    "offer": "ERR_OFFER_NOT_FOUND",
    "valuation": "ERR_VALUATION_NOT_FOUND",
    "dispute": "ERR_DISPUTE_NOT_FOUND",
    "lien": "ERR_LIEN_NOT_FOUND",
    "mi_claim": "ERR_MI_CLAIM_NOT_FOUND",
    "approval": "ERR_APPROVAL_NOT_FOUND",
    "extension": "ERR_EXTENSION_NOT_FOUND",
    "vendor": "ERR_VENDOR_NOT_FOUND",
}
