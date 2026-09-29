"""Error catalogue (PRD §5 / scaffold §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- HTTP status per error id (PRD §5) ------------------------------------
STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_CENTER_NOT_FOUND": 404,
    "ERR_BERTH_NOT_FOUND": 404,
    "ERR_VESSEL_NOT_FOUND": 404,
    "ERR_VEHICLE_NOT_FOUND": 404,
    "ERR_SURVEY_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_REPAIR_ORDER_NOT_FOUND": 404,
    "ERR_KIT_NOT_FOUND": 404,
    "ERR_WORK_ORDER_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_HOLD_ORDER_NOT_FOUND": 404,
    "ERR_DEALER_NOT_FOUND": 404,
    "ERR_CARRIER_NOT_FOUND": 404,
    "ERR_RELEASE_ORDER_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_KEY": 409,
    "ERR_STALE_VEHICLE_VERSION": 412,
    "ERR_STALE_SURVEY_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_VEHICLE_STOP_SHIP_BLOCKED": 409,
    "ERR_VEHICLE_DAMAGE_BLOCKED": 409,
    "ERR_CLAIM_REQUIRED": 409,
    "ERR_YARD_GRIDLOCK": 409,
    "ERR_BERTH_WINDOW_CONFLICT": 409,
    "ERR_BERTH_WINDOW_NOT_OPEN": 409,
    "ERR_CARRIER_WINDOW_CAPACITY": 409,
    "ERR_VESSEL_DISCHARGE_INCOMPLETE": 409,
    "ERR_ACCESSORY_WORK_OPEN": 409,
    "ERR_KIT_INSUFFICIENT": 409,
    "ERR_CLAIM_REVISION_LIMIT": 409,
    "ERR_CLAIM_NOT_WARRANTED": 409,
    "ERR_CLAIM_ALREADY_OPEN": 409,
    "ERR_NO_ELIGIBLE_CARRIER": 409,
    "ERR_NO_UNITS_DISCHARGED": 409,
    "ERR_DEALER_QUOTA_EXCEEDED": 409,
    "ERR_SETTLEMENT_EXCEEDS_RECOVERABLE": 422,
}


def fail(error_id, message=None):
    raise ApiError(error_id, STATUS[error_id], message)


def invalid(message):
    raise ApiError("ERR_INVALID_REQUEST", 400, message)


def invalid_state(message="The requested transition is not available from the current state"):
    raise ApiError("ERR_INVALID_STATE", 409, message)
