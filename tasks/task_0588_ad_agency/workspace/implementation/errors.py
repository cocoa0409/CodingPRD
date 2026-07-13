"""Error catalogue for the Ad Agency Ops API (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
        self.http_status = http_status or HTTP_STATUS[error_id]


HTTP_STATUS = {
    "ERR_INVALID_REQUEST": 400,
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CLIENT_NOT_FOUND": 404,
    "ERR_RATE_CARD_NOT_FOUND": 404,
    "ERR_STAFF_MEMBER_NOT_FOUND": 404,
    "ERR_RETAINER_NOT_FOUND": 404,
    "ERR_SOW_NOT_FOUND": 404,
    "ERR_CAMPAIGN_NOT_FOUND": 404,
    "ERR_DELIVERABLE_NOT_FOUND": 404,
    "ERR_TIME_ENTRY_NOT_FOUND": 404,
    "ERR_VENDOR_COST_NOT_FOUND": 404,
    "ERR_MEDIA_PLAN_NOT_FOUND": 404,
    "ERR_MEDIA_PLACEMENT_NOT_FOUND": 404,
    "ERR_INSERTION_ORDER_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_SOW_NOT_COUNTERSIGNED": 409,
    "ERR_SOW_EXPIRED": 409,
    "ERR_CAMPAIGN_ON_HOLD": 409,
    "ERR_MEDIA_PLAN_NOT_APPROVED": 409,
    "ERR_PLACEMENT_FLIGHT_CONFLICT": 409,
    "ERR_TIME_ENTRY_OVERLAP": 409,
    "ERR_PLACEMENT_NOT_ELIGIBLE": 422,
    "ERR_DAILY_MINUTES_EXCEEDED": 422,
    "ERR_SOW_LABOR_CAP_EXCEEDED": 422,
    "ERR_MEDIA_BUDGET_EXCEEDED": 422,
    "ERR_REVISION_LIMIT_EXCEEDED": 422,
    "ERR_INVOICE_NO_LINES": 422,
    "ERR_PAYMENT_EXCEEDS_BALANCE": 422,
    "ERR_STALE_MEDIA_PLAN_VERSION": 412,
    "ERR_STALE_RETAINER_VERSION": 412,
}

DEFAULT_MESSAGES = {
    "ERR_INVALID_REQUEST": "The request is malformed.",
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or invalid.",
    "ERR_FORBIDDEN_ROLE": "The caller's role is not authorised for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The caller does not own this resource.",
    "ERR_SEGREGATION_OF_DUTIES": "The approver may not be the person who logged the work.",
    "ERR_INVALID_STATE": "The resource is not in a state that allows this transition.",
    "ERR_SOW_NOT_COUNTERSIGNED": "The governing statement of work is not countersigned.",
    "ERR_SOW_EXPIRED": "The governing statement of work has expired.",
    "ERR_CAMPAIGN_ON_HOLD": "The owning campaign is on hold.",
    "ERR_MEDIA_PLAN_NOT_APPROVED": "The owning media plan is not approved.",
    "ERR_PLACEMENT_FLIGHT_CONFLICT": "The flight collides with an existing booking on this placement.",
    "ERR_TIME_ENTRY_OVERLAP": "The interval overlaps another time entry of this staff member.",
    "ERR_PLACEMENT_NOT_ELIGIBLE": "The placement's channel is not whitelisted on this media plan.",
    "ERR_DAILY_MINUTES_EXCEEDED": "The daily minute cap would be exceeded.",
    "ERR_SOW_LABOR_CAP_EXCEEDED": "The statement of work's labor cap would be exceeded.",
    "ERR_MEDIA_BUDGET_EXCEEDED": "The media plan's uncommitted budget would be exceeded.",
    "ERR_REVISION_LIMIT_EXCEEDED": "The deliverable's revision limit has been reached.",
    "ERR_INVOICE_NO_LINES": "The invoice assembled zero lines.",
    "ERR_PAYMENT_EXCEEDS_BALANCE": "The payment would exceed the invoice's cash due.",
    "ERR_STALE_MEDIA_PLAN_VERSION": "The supplied media plan version is stale.",
    "ERR_STALE_RETAINER_VERSION": "The supplied retainer version is stale.",
}
