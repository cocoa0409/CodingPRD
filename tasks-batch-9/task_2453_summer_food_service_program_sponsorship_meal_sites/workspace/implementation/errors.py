"""Error catalog (PRD sec 5) and the ApiError exception."""

ERROR_STATUS = {
    # authentication / authorisation
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    # request well-formedness
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_SPONSOR_NOT_FOUND": 404,
    "ERR_AREA_RECORD_NOT_FOUND": 404,
    "ERR_BUDGET_NOT_FOUND": 404,
    "ERR_ADVANCE_NOT_FOUND": 404,
    "ERR_SITE_NOT_FOUND": 404,
    "ERR_SERVICE_DAY_NOT_FOUND": 404,
    "ERR_COUNT_ENTRY_NOT_FOUND": 404,
    "ERR_HOLDING_LOG_NOT_FOUND": 404,
    "ERR_VISIT_NOT_FOUND": 404,
    "ERR_CORRECTIVE_ACTION_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_CLAIM_LINE_ITEM_NOT_FOUND": 404,
    # ownership / segregation of duties
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # same-entity state
    "ERR_SPONSOR_STATE_INVALID": 409,
    "ERR_BUDGET_STATE_INVALID": 409,
    "ERR_ADVANCE_STATE_INVALID": 409,
    "ERR_SITE_STATE_INVALID": 409,
    "ERR_SERVICE_DAY_STATE_INVALID": 409,
    "ERR_VISIT_STATE_INVALID": 409,
    "ERR_ACTION_STATE_INVALID": 409,
    "ERR_CLAIM_STATE_INVALID": 409,
    # cross-entity readiness
    "ERR_SPONSOR_NOT_APPROVED": 409,
    "ERR_SITE_NOT_APPROVED": 409,
    "ERR_SITE_SUSPENDED": 409,
    "ERR_SITE_NOT_OPERATING": 409,
    "ERR_BUDGET_NOT_APPROVED": 409,
    # optimistic concurrency
    "ERR_STALE_SPONSOR_VERSION": 412,
    # food safety / eligibility
    "ERR_FOOD_SAFETY_BREACH": 409,
    "ERR_MEASURED_BEFORE_FOOD_RECEIVED": 422,
    "ERR_ELIGIBILITY_NOT_DETERMINED": 409,
    "ERR_SITE_NOT_ELIGIBLE": 409,
    # referential coherence
    "ERR_MEAL_TYPE_NOT_APPROVED": 422,
    "ERR_REVERSAL_TARGET_INVALID": 422,
    "ERR_SITE_SPONSOR_MISMATCH": 422,
    "ERR_AREA_RECORD_REQUIRED": 422,
    "ERR_ENROLLED_PCT_REQUIRED": 422,
    # structural / uniqueness
    "ERR_MEAL_TYPE_COUNT_EXCEEDED": 422,
    "ERR_DUPLICATE_AREA_RECORD": 409,
    "ERR_DUPLICATE_SERVICE_DAY": 409,
    "ERR_DUPLICATE_CLAIM_MONTH": 409,
    "ERR_DUPLICATE_CLAIM_LINE_ITEM": 409,
    "ERR_NO_FINALIZED_DAYS": 422,
    "ERR_CLAIM_HAS_NO_LINE_ITEMS": 422,
    "ERR_CLAIM_HOLD_BLOCKING": 409,
    "ERR_INSUFFICIENT_FORECAST_HISTORY": 422,
    "ERR_DAY_HAS_OPEN_SERVICE": 409,
    "ERR_NO_APPROVED_SITE": 409,
    # temporal
    "ERR_SERVICE_DATE_OUTSIDE_SEASON": 422,
    "ERR_MEAL_SERVICE_WINDOW_CONFLICT": 409,
    "ERR_MONITOR_SCHEDULE_CONFLICT": 409,
    "ERR_MONITOR_DAILY_CAP_EXCEEDED": 409,
    "ERR_VISIT_DATE_NOT_REACHED": 409,
    "ERR_DEMAND_TOO_EARLY": 409,
    "ERR_ESCALATION_NOT_DUE": 409,
    # fiscal
    "ERR_ADMIN_RATIO_EXCEEDED": 422,
    "ERR_APPROVED_CEILING_EXCEEDS_REQUEST": 422,
    "ERR_APPROVED_EXCEEDS_REQUESTED": 422,
    "ERR_ADVANCE_EXCEEDS_CAP": 422,
    "ERR_SPONSOR_NOT_ADVANCE_ELIGIBLE": 422,
    "ERR_OPERATING_COST_EXCEEDS_BUDGET": 422,
    "ERR_ADMIN_COST_EXCEEDS_BUDGET": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or the role is not recognised.",
    "ERR_ROLE_NOT_PERMITTED": "The caller's role may not perform this operation.",
    "ERR_INVALID_REQUEST": "The request is malformed.",
    "ERR_NOT_RESOURCE_OWNER": "The caller does not own the addressed resource.",
    "ERR_SEGREGATION_OF_DUTIES": "The caller may not act on a record they created.",
    "ERR_STALE_SPONSOR_VERSION": "The supplied sponsor version does not match the stored version.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )
        super(ApiError, self).__init__(self.message)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
