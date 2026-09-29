"""Error catalogue (PRD section 5) and the ApiError exception."""

HTTP_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_ARTIST_NOT_FOUND": 404,
    "ERR_SITE_NOT_FOUND": 404,
    "ERR_ARTWORK_NOT_FOUND": 404,
    "ERR_PROTOCOL_NOT_FOUND": 404,
    "ERR_VISIT_NOT_FOUND": 404,
    "ERR_ASSESSMENT_NOT_FOUND": 404,
    "ERR_CONSERVATOR_NOT_FOUND": 404,
    "ERR_PROPOSAL_NOT_FOUND": 404,
    "ERR_CONSULTATION_NOT_FOUND": 404,
    "ERR_NOTICE_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_POOL_NOT_FOUND": 404,
    "ERR_ALLOCATION_NOT_FOUND": 404,
    "ERR_INCIDENT_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_ARTWORK_VERSION": 412,
    "ERR_STALE_POOL_VERSION": 412,
    # state preconditions
    "ERR_ASSESSMENT_INVALID_STATE": 409,
    "ERR_PROPOSAL_INVALID_STATE": 409,
    "ERR_VISIT_INVALID_STATE": 409,
    "ERR_CASE_INVALID_STATE": 409,
    "ERR_NOTICE_INVALID_STATE": 409,
    "ERR_CONSULTATION_INVALID_STATE": 409,
    "ERR_ALLOCATION_INVALID_STATE": 409,
    "ERR_INCIDENT_INVALID_STATE": 409,
    "ERR_CLAIM_INVALID_STATE": 409,
    # compliance / safety / segregation of duties
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_INITIATOR_CANNOT_VOTE": 409,
    "ERR_ARTWORK_DEACCESSIONED": 409,
    "ERR_ARTWORK_CUSTODY_INVALID": 409,
    "ERR_RECOGNIZED_STATURE_PROTECTED": 422,
    "ERR_ARTIST_CONSULTATION_REQUIRED": 422,
    "ERR_ARTIST_CONSULTATION_PENDING": 409,
    "ERR_ARTIST_OBJECTION_UNRESOLVED": 409,
    "ERR_MORAL_RIGHTS_NOTICE_REQUIRED": 422,
    "ERR_MORAL_RIGHTS_WAIT_ACTIVE": 409,
    "ERR_CONSERVATOR_NOT_ELIGIBLE": 422,
    "ERR_PROTOCOL_MATERIAL_MISMATCH": 422,
    "ERR_PHOTO_DOCUMENTATION_INSUFFICIENT": 422,
    # temporal
    "ERR_WINDOW_IN_PAST": 422,
    "ERR_VISIT_WINDOW_NOT_OPEN": 409,
    "ERR_PUBLIC_COMMENT_OPEN": 409,
    "ERR_CONSULTATION_WINDOW_CLOSED": 409,
    # constraints
    "ERR_DUPLICATE_CODE": 409,
    "ERR_CONSERVATOR_WINDOW_CONFLICT": 409,
    "ERR_SITE_WORK_CAPACITY_CONFLICT": 409,
    "ERR_SITE_CAPACITY_EXCEEDED": 422,
    "ERR_DUPLICATE_ACTIVE_PROPOSAL": 409,
    "ERR_ASSESSMENT_NOT_FINALIZED": 422,
    "ERR_MAX_ANNUAL_APPLICATIONS": 409,
    "ERR_DUPLICATE_BALLOT": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    # referential
    "ERR_DISPOSITION_TARGET_REQUIRED": 422,
    "ERR_ALLOCATION_LINK_MISMATCH": 422,
    "ERR_CLAIM_BASIS_UNSUPPORTED": 422,
    "ERR_CREDIT_POOL_REQUIRED": 422,
    # fiscal
    "ERR_POOL_FUNDS_INSUFFICIENT": 422,
    "ERR_FUNDING_NOT_RESERVED": 422,
    "ERR_NO_SETTLEMENT_PAYABLE": 422,
    # generic transport level fallbacks
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or the declared role is unknown.",
    "ERR_UNAUTHORIZED": "The acting role is not authorized for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting user does not own the referenced resource.",
    "ERR_INVALID_REQUEST": "The request body is invalid.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = HTTP_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )
