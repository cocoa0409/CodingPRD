"""Error catalog (PRD section 5 / SCAFFOLD 1.6) and the ApiError exception."""

ERROR_HTTP = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # not found
    "ERR_OUTAGE_NOT_FOUND": 404,
    "ERR_SPENT_FUEL_POOL_NOT_FOUND": 404,
    "ERR_RAD_AREA_NOT_FOUND": 404,
    "ERR_SAFETY_FUNCTION_NOT_FOUND": 404,
    "ERR_WORK_ORDER_NOT_FOUND": 404,
    "ERR_SCHEDULE_ACTIVITY_NOT_FOUND": 404,
    "ERR_CORE_LOAD_PATTERN_NOT_FOUND": 404,
    "ERR_POOL_RESERVATION_NOT_FOUND": 404,
    "ERR_WORKER_NOT_FOUND": 404,
    "ERR_RWP_NOT_FOUND": 404,
    "ERR_EMERGENT_ITEM_NOT_FOUND": 404,
    "ERR_STARTUP_TEST_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # own-state preconditions
    "ERR_OUTAGE_STATE_INVALID": 409,
    "ERR_WORK_ORDER_STATE_INVALID": 409,
    "ERR_ACTIVITY_STATE_INVALID": 409,
    "ERR_CORE_LOAD_PATTERN_STATE_INVALID": 409,
    "ERR_POOL_RESERVATION_STATE_INVALID": 409,
    "ERR_WORKER_STATE_INVALID": 409,
    "ERR_RWP_STATE_INVALID": 409,
    "ERR_EMERGENT_ITEM_STATE_INVALID": 409,
    "ERR_STARTUP_TEST_STATE_INVALID": 409,
    # cross-entity state guards
    "ERR_WORK_ORDER_NOT_APPROVED": 409,
    "ERR_CORE_LOAD_PATTERN_NOT_APPROVED": 409,
    "ERR_PREDECESSOR_NOT_COMPLETE": 409,
    "ERR_OPEN_WORK_ORDERS_REMAIN": 409,
    "ERR_STARTUP_SEQUENCE_EMPTY": 409,
    "ERR_BADGED_WORKFORCE_INSUFFICIENT": 409,
    # optimistic concurrency
    "ERR_OUTAGE_VERSION_STALE": 412,
    "ERR_POOL_VERSION_STALE": 412,
    # nuclear / radiological safety
    "ERR_SHUTDOWN_MARGIN_INSUFFICIENT": 422,
    "ERR_ALARA_POSTURE_SUSPENDED": 409,
    "ERR_ALARA_REVIEW_REQUIRED": 422,
    "ERR_REGULATORY_HOLD_POINT_NOT_RELEASED": 422,
    "ERR_SAFETY_FUNCTION_CAPACITY_EXCEEDED": 409,
    # referential graph integrity
    "ERR_PREDECESSOR_OUTAGE_MISMATCH": 422,
    "ERR_ACTIVITY_CYCLE": 422,
    # temporal windows
    "ERR_RAD_AREA_WINDOW_CONFLICT": 409,
    # administrative constraints
    "ERR_STARTUP_SEQUENCE_OUT_OF_ORDER": 409,
    "ERR_STARTUP_SEQUENCE_DUPLICATE": 409,
    "ERR_BADGE_NUMBER_TAKEN": 409,
    "ERR_SCOPE_FROZEN": 409,
    # fiscal / capacity budgets
    "ERR_POOL_CAPACITY_EXCEEDED": 409,
    "ERR_DOSE_BUDGET_EXCEEDED": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or invalid X-User-ID / X-User-Role headers.",
    "ERR_UNAUTHORIZED": "The acting role is not authorized for this endpoint.",
    "ERR_INVALID_REQUEST": "The request body or query is malformed.",
}


def api_error(error_id, message=None):
    return ApiError(error_id, message)
