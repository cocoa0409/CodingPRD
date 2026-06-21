"""Error catalogue (PRD §5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue: error_id -> HTTP status code (PRD §5 / scaffold Table 6)
ERROR_CATALOG = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_NOT_ACCOUNT_OWNER": 403,
    "ERR_ADDRESS_NOT_SERVICEABLE": 409,
    "ERR_PLAN_EXCEEDS_SERVICEABLE_SPEED": 409,
    "ERR_SELF_INSTALL_NOT_ELIGIBLE": 409,
    "ERR_SLOT_AT_CAPACITY": 409,
    "ERR_TECHNICIAN_DOUBLE_BOOKED": 409,
    "ERR_APPOINTMENT_OUTSIDE_SLOT": 422,
    "ERR_OUTAGE_BELOW_SLA": 409,
    "ERR_CYCLE_HAS_OPEN_OUTAGE": 409,
    "ERR_NO_EQUIPMENT_AVAILABLE": 409,
    "ERR_STALE_ACCOUNT_VERSION": 412,
    "ERR_DUPLICATE_SERIAL": 409,
    "ERR_DUPLICATE_PLAN_CODE": 409,
    "ERR_USAGE_OUTSIDE_CYCLE": 422,
    "ERR_OUTAGE_OUTSIDE_CYCLE": 422,
    "ERR_CYCLE_NOT_CLOSED": 409,
    "ERR_ACCOUNT_NOT_ACTIVE": 409,
}


def err(error_id, message=None):
    """Raise an ApiError for a catalogued error_id."""
    http = ERROR_CATALOG.get(error_id, 400)
    raise ApiError(error_id, http, message)
