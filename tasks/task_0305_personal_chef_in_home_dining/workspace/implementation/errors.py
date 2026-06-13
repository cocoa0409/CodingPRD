"""Error catalog and the ApiError exception. Codes/HTTP statuses come verbatim
from PRD §5 Error Code Catalogue and SCAFFOLD §1.6."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


# HTTP status per error_id (PRD §5 / SCAFFOLD §1.6)
ERROR_HTTP = {
    "ERR_MISSING_AUTH_CONTEXT": 401,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_CHEF_NOT_FOUND": 404,
    "ERR_MENU_NOT_FOUND": 404,
    "ERR_ZONE_NOT_FOUND": 404,
    "ERR_CLIENT_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_RESCHEDULE_NOT_FOUND": 404,
    "ERR_GROCERY_RUN_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_CHEF_NOT_ACTIVE": 409,
    "ERR_BOOKING_NOT_CONFIRMED": 409,
    "ERR_GROCERY_RUN_NOT_FINALIZED": 409,
    "ERR_GROCERY_RUN_EMPTY": 422,
    "ERR_ALLERGEN_CONFLICT": 422,
    "ERR_EQUIPMENT_UNAVAILABLE": 422,
    "ERR_PARTY_SIZE_OUT_OF_RANGE": 422,
    "ERR_ZIP_OUTSIDE_SERVICE_AREA": 422,
    "ERR_CHEF_TIME_CONFLICT": 409,
    "ERR_DAILY_CAPACITY_EXCEEDED": 409,
    "ERR_NO_LISTED_MENU": 409,
    "ERR_NO_TRAVEL_ZONE": 409,
    "ERR_DEPOSIT_AMOUNT_MISMATCH": 402,
    "ERR_BALANCE_AMOUNT_MISMATCH": 402,
    "ERR_BALANCE_OUTSTANDING": 402,
    # Not-found codes for entities addressed by id on GET that the PRD §5
    # catalogue does not enumerate (AvailabilityBlock, Payment). The PRD's
    # not-found family is all 404; these mirror that status so an unknown id on
    # GET /availability-blocks/{id} or /payments/{id} yields a well-formed 404.
    "ERR_BLOCK_NOT_FOUND": 404,
    "ERR_PAYMENT_NOT_FOUND": 404,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_HTTP[error_id], message)
