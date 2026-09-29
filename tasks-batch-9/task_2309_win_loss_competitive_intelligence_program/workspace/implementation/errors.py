"""Error catalogue (PRD 5) and the ApiError exception."""

HTTP_STATUS = {
    # auth
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_ANALYST_IDENTITY_INVALID": 403,
    # existence
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_COMPETITOR_NOT_FOUND": 404,
    "ERR_DEAL_NOT_FOUND": 404,
    "ERR_ANALYST_NOT_FOUND": 404,
    "ERR_BUYER_CONTACT_NOT_FOUND": 404,
    "ERR_SAMPLING_FRAME_NOT_FOUND": 404,
    "ERR_INTERVIEW_NOT_FOUND": 404,
    "ERR_INTERVIEW_RESPONSE_NOT_FOUND": 404,
    "ERR_LOSS_REASON_NOT_FOUND": 404,
    "ERR_LOSS_ATTRIBUTION_NOT_FOUND": 404,
    "ERR_BATTLECARD_NOT_FOUND": 404,
    "ERR_BATTLECARD_CLAIM_NOT_FOUND": 404,
    "ERR_PRODUCT_GAP_NOT_FOUND": 404,
    "ERR_ENABLEMENT_ASSIGNMENT_NOT_FOUND": 404,
    # structural / range
    "ERR_INVALID_REQUEST": 400,
    "ERR_VALUE_OUT_OF_RANGE": 422,
    "ERR_INVALID_TIME_WINDOW": 422,
    # tenancy / uniqueness / concurrency
    "ERR_CROSS_PROGRAM_REFERENCE": 409,
    "ERR_DUPLICATE_RESOURCE_KEY": 409,
    "ERR_STALE_DEAL_VERSION": 412,
    "ERR_STALE_PROGRAM_VERSION": 412,
    # state
    "ERR_PROGRAM_STATE_INVALID": 409,
    "ERR_DEAL_STATE_INVALID": 409,
    "ERR_FRAME_STATE_INVALID": 409,
    "ERR_INTERVIEW_STATE_INVALID": 409,
    "ERR_ATTRIBUTION_STATE_INVALID": 409,
    "ERR_BATTLECARD_STATE_INVALID": 409,
    "ERR_CLAIM_STATE_INVALID": 409,
    "ERR_PRODUCT_GAP_STATE_INVALID": 409,
    "ERR_ASSIGNMENT_STATE_INVALID": 409,
    # posture and business rules
    "ERR_PROGRAM_POSTURE_FROZEN": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INDEPENDENCE_VIOLATION": 422,
    "ERR_ANALYST_NOT_CERTIFIED": 422,
    "ERR_CONSENT_NOT_GRANTED": 422,
    "ERR_CONTACT_COOLING_OFF_ACTIVE": 409,
    "ERR_ANALYST_SLOT_CONFLICT": 409,
    "ERR_DEAL_OUTSIDE_FRAME_WINDOW": 422,
    "ERR_ANALYST_CAPACITY_EXCEEDED": 409,
    "ERR_STRATUM_QUOTA_EXHAUSTED": 409,
    "ERR_NO_ELIGIBLE_DEALS": 422,
    "ERR_GUIDE_COVERAGE_INCOMPLETE": 422,
    "ERR_REASON_NOT_LEAF": 422,
    "ERR_REASON_DEPRECATED": 422,
    "ERR_TAXONOMY_DEPTH_EXCEEDED": 422,
    "ERR_TAXONOMY_CYCLE": 409,
    "ERR_WEIGHT_SPLIT_INVALID": 422,
    "ERR_CLAIM_UNSUBSTANTIATED": 422,
    "ERR_RISK_CEILING_EXCEEDED": 422,
    "ERR_INCENTIVE_BUDGET_EXCEEDED": 402,
    "ERR_ADOPTION_BELOW_THRESHOLD": 409,
    "ERR_ASSIGNMENT_PAST_DUE": 409,
    "ERR_RESCHEDULE_LIMIT_REACHED": 409,
    "ERR_RESPONSE_NOT_PRODUCT_GAP": 422,
    "ERR_EVIDENCE_SET_INVALID": 422,
}

DEFAULT_MESSAGE = {
    "ERR_MISSING_AUTH_HEADERS": "Both X-User-ID and X-User-Role headers are required.",
    "ERR_UNKNOWN_ROLE": "X-User-Role is not one of the six declared roles.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not authorized for this operation.",
    "ERR_ANALYST_IDENTITY_INVALID": "X-User-ID does not resolve to an ACTIVE Analyst.",
    "ERR_INVALID_REQUEST": "The request payload or query string is structurally invalid.",
    "ERR_VALUE_OUT_OF_RANGE": "A numeric value falls outside its declared domain.",
    "ERR_INVALID_TIME_WINDOW": "The interval start must be strictly before its end.",
    "ERR_CROSS_PROGRAM_REFERENCE": "A referenced row belongs to a different program.",
    "ERR_DUPLICATE_RESOURCE_KEY": "A scoped uniqueness key is already taken.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = HTTP_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGE.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )


def fail(error_id, message=None):
    raise ApiError(error_id, message)
