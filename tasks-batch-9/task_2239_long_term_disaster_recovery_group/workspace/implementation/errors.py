"""Error catalogue (PRD section 5) and the API exception type."""

ERROR_HTTP_STATUS = {
    # auth / authz
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_ORG_IDENTITY_MISMATCH": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CASE_MANAGER_MISMATCH": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_SURVIVOR_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_DAMAGE_ITEM_NOT_FOUND": 404,
    "ERR_ASSESSMENT_NOT_FOUND": 404,
    "ERR_MEMBER_ORG_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_PRESENTATION_NOT_FOUND": 404,
    "ERR_COMMITMENT_NOT_FOUND": 404,
    "ERR_FUNDING_SOURCE_NOT_FOUND": 404,
    "ERR_DISBURSEMENT_NOT_FOUND": 404,
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_VOLUNTEER_GROUP_NOT_FOUND": 404,
    "ERR_DEPLOYMENT_NOT_FOUND": 404,
    "ERR_LODGING_SITE_NOT_FOUND": 404,
    "ERR_HOUSING_ASSIGNMENT_NOT_FOUND": 404,
    # state
    "ERR_CASE_NOT_ASSESSABLE": 409,
    "ERR_CASE_INVALID_STATE": 409,
    "ERR_SESSION_NOT_ACCEPTING_QUEUE": 409,
    "ERR_SESSION_NOT_IN_SESSION": 409,
    "ERR_SESSION_HAS_ACTIVE_PRESENTATION": 409,
    "ERR_PRESENTATION_INVALID_STATE": 409,
    "ERR_PRESENTATION_ALREADY_ACTIVE": 409,
    "ERR_PRESENTATION_NOT_ACCEPTING_PLEDGES": 409,
    "ERR_COMMITMENT_INVALID_STATE": 409,
    "ERR_DISBURSEMENT_INVALID_STATE": 409,
    "ERR_PROJECT_INVALID_TRANSITION": 409,
    "ERR_DEPLOYMENT_INVALID_TRANSITION": 409,
    "ERR_HOUSING_ALREADY_RELEASED": 409,
    "ERR_DAMAGE_ITEM_ALREADY_VERIFIED": 409,
    "ERR_MEMBER_ORG_NOT_ACTIVE": 409,
    "ERR_PROJECT_NOT_PAYABLE": 409,
    "ERR_PROJECT_NOT_ACCEPTING_VOLUNTEERS": 409,
    "ERR_PREDECESSOR_NOT_COMPLETE": 409,
    "ERR_PREDECESSOR_CASE_MISMATCH": 422,
    # optimistic concurrency
    "ERR_STALE_PRESENTATION_VERSION": 412,
    "ERR_STALE_CASE_VERSION": 412,
    # business rules
    "ERR_NO_VERIFIED_DAMAGE": 422,
    "ERR_ASSESSMENT_STALE": 409,
    "ERR_ASSESSMENT_VARIANT_NOT_ELIGIBLE": 422,
    "ERR_ASSESSMENT_CASE_MISMATCH": 422,
    "ERR_QUORUM_NOT_MET": 409,
    "ERR_ORG_NOT_IN_SESSION": 409,
    "ERR_NOT_AT_QUEUE_HEAD": 409,
    "ERR_MAX_DEFERRALS_REACHED": 409,
    "ERR_DUPLICATION_OF_BENEFITS": 422,
    "ERR_RESTRICTION_MISMATCH": 422,
    "ERR_INSUFFICIENT_RESTRICTED_FUNDS": 422,
    "ERR_DISBURSEMENT_EXCEEDS_COMMITMENT": 422,
    "ERR_PLEDGE_CAP_EXCEEDED": 422,
    "ERR_AWARD_EXCEEDS_UNMET_NEED": 422,
    "ERR_AWARD_ZERO": 422,
    "ERR_INVALID_DATE_RANGE": 422,
    "ERR_DEPLOYMENT_WINDOW_CONFLICT": 409,
    "ERR_LODGING_CAPACITY_EXCEEDED": 409,
    "ERR_SKILL_FIT_BELOW_MINIMUM": 422,
    "ERR_CLOSURE_CRITERIA_NOT_MET": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or unknown authentication headers.",
    "ERR_UNAUTHORIZED_ROLE": "Role is not permitted to perform this operation.",
    "ERR_ORG_IDENTITY_MISMATCH": "Acting member organization does not match the target organization.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties prevents this actor from performing this action.",
    "ERR_CASE_MANAGER_MISMATCH": "Acting user is not the assigned case manager for this case.",
    "ERR_INVALID_REQUEST": "Request body or query parameters are invalid.",
}


class ApiError(Exception):
    """Raised anywhere in the request path; rendered by the Flask error handler."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )
