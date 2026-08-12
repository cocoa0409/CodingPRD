"""Error catalog: ids and HTTP statuses from SCAFFOLD §1.6 / PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id, status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.status = status
        self.message = message or error_id


# --- catalog (id -> http status) ---
CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_RESIDENT_SUSPENDED": 403,
    "ERR_INVALID_WINDOW": 422,
    "ERR_WINDOW_IN_PAST": 422,
    "ERR_PICKUP_WINDOW_CONFLICT": 409,
    "ERR_KIT_LIMIT_EXCEEDED": 409,
    "ERR_RESCHEDULE_LIMIT_REACHED": 409,
    "ERR_REBOOK_LIMIT_REACHED": 409,
    "ERR_BAGS_NOT_DELIVERED": 409,
    "ERR_ROUTE_CAPACITY_EXCEEDED": 409,
    "ERR_DROPBOX_NOT_FULL": 409,
    "ERR_TICKET_NOT_CERTIFIED": 409,
    "ERR_TICKET_QUARANTINED": 409,
    "ERR_CREDIT_EXISTS": 409,
    "ERR_OPEN_REPORTS_REMAIN": 409,
    "ERR_REPORT_WINDOW_CLOSED": 409,
    "ERR_NO_ELIGIBLE_PARTNER": 422,
    "ERR_PARTNER_CAPACITY_EXCEEDED": 409,
    "ERR_ASSIGNMENT_PENDING_EXISTS": 409,
    "ERR_SPLIT_SUM_INVALID": 422,
    "ERR_FUND_ALREADY_ACTIVE": 409,
    "ERR_FUND_NOT_ACTIVE": 409,
    "ERR_FUND_INSUFFICIENT": 409,
    "ERR_CREDIT_NOT_FINAL": 409,
    "ERR_PERIOD_OVERLAP": 409,
    "ERR_PERIOD_NOT_OPEN": 409,
    "ERR_OPEN_TICKETS_REMAIN": 409,
}


def fail(error_id, message=""):
    status = CATALOG.get(error_id, 500)
    raise ApiError(error_id, status, message or error_id)
