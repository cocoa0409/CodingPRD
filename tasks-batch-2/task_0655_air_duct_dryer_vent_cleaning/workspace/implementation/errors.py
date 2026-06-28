"""Error catalog: every error_id mapped to its HTTP status (PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status per error_id (PRD §5 / scaffold §1.6)
ERROR_STATUS = {
    # Auth
    "ERR_MISSING_OR_INVALID_USER_CONTEXT": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    # Not found
    "ERR_HOME_NOT_FOUND": 404,
    "ERR_HOMEOWNER_NOT_FOUND": 404,
    "ERR_SYSTEM_NOT_FOUND": 404,
    "ERR_WORK_ORDER_NOT_FOUND": 404,
    "ERR_ROUTE_NOT_FOUND": 404,
    "ERR_CREW_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_FOUND": 404,
    "ERR_TICKET_NOT_FOUND": 404,
    "ERR_PRICING_CONFIG_NOT_FOUND": 404,
    # Request shape
    "ERR_INVALID_REQUEST": 400,
    # WorkOrder state
    "ERR_WORK_ORDER_BAD_STATE": 409,
    "ERR_WORK_ORDER_ALREADY_SCHEDULED": 409,
    "ERR_SYSTEM_NOT_ACTIVE": 409,
    "ERR_NO_ACTIVE_PRICING_CONFIG": 409,
    "ERR_PRICING_CONFIG_ALREADY_ACTIVE": 409,
    "ERR_INSUFFICIENT_AFTER_PHOTOS": 422,
    # RoutePlan state & commit
    "ERR_ROUTE_BAD_STATE": 409,
    "ERR_ROUTE_NOT_OPEN": 409,
    "ERR_ROUTE_NOT_LOCKED": 409,
    "ERR_ROUTE_EMPTY": 409,
    "ERR_ROUTE_HAS_OPEN_WORK": 409,
    "ERR_ZONE_MISMATCH": 422,
    "ERR_CREW_NOT_UV_CERTIFIED": 422,
    "ERR_OUTSIDE_SHIFT": 422,
    "ERR_SLOT_OVERLAP": 409,
    "ERR_CREW_DOUBLE_BOOKED": 409,
    "ERR_STALE_ROUTE_VERSION": 412,
    # RecurringPlan
    "ERR_PLAN_BAD_STATE": 409,
    "ERR_PLAN_NOT_ACTIVE": 409,
    "ERR_REMINDER_NOT_DUE": 409,
    "ERR_PLAN_ALREADY_EXISTS": 409,
    "ERR_STALE_HOME_VERSION": 412,
    # UpsellReferral
    "ERR_REFERRAL_BAD_STATE": 409,
    # CallbackTicket
    "ERR_TICKET_BAD_STATE": 409,
    "ERR_WORK_ORDER_NOT_COMPLETED": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
