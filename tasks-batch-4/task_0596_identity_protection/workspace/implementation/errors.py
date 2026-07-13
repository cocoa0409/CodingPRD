"""Error catalogue (PRD §5 / SCAFFOLD §1.6)."""


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_SUBSCRIBER_NOT_FOUND": 404,
    "ERR_FAMILY_MEMBER_NOT_FOUND": 404,
    "ERR_BUREAU_PROFILE_NOT_FOUND": 404,
    "ERR_ALERT_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_SPECIALIST_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_WALLET_ITEM_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_VERIFICATION_TOKEN": 422,
    "ERR_STALE_CASE_VERSION": 412,
    "ERR_STALE_SPECIALIST_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_CASE_NOT_RESOLVED": 409,
    "ERR_ENROLLMENT_NOT_ACTIVE": 409,
    "ERR_SPECIALIST_TIER_INSUFFICIENT": 409,
    "ERR_SPECIALIST_AT_CAPACITY": 409,
    "ERR_NO_ELIGIBLE_SPECIALIST": 409,
    "ERR_ENGAGEMENT_CAPACITY_EXCEEDED": 409,
    "ERR_THAW_WINDOW_OVERLAP": 409,
    "ERR_INVALID_WINDOW": 422,
    "ERR_WINDOW_IN_PAST": 422,
    "ERR_FAMILY_LIMIT_EXCEEDED": 409,
    "ERR_FAMILY_MEMBER_MISMATCH": 409,
    "ERR_CHILD_MONITORING_NOT_INCLUDED": 409,
    "ERR_INSURANCE_EXHAUSTED": 409,
    "ERR_UNDERWRITING_RISK_TOO_HIGH": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or invalid.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not permitted to call this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The caller does not own the target resource.",
    "ERR_SEGREGATION_OF_DUTIES": "The same operator may not both approve and pay a claim.",
    "ERR_INVALID_REQUEST": "The request body is invalid.",
    "ERR_INVALID_STATE": "The requested transition is not declared from the resource's current state.",
}
