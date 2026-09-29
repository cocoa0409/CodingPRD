"""Error catalogue (PRD section 5 / SCAFFOLD section 1.6)."""


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_FACILITY_SCOPE_VIOLATION": 403,
    "ERR_PARTNER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_TIME_WINDOW": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_MODEL_NOT_FOUND": 404,
    "ERR_REVISION_NOT_FOUND": 404,
    "ERR_TEST_RESOURCE_NOT_FOUND": 404,
    "ERR_FIRMWARE_NOT_FOUND": 404,
    "ERR_FACILITY_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_PARTNER_NOT_FOUND": 404,
    "ERR_INSTALL_JOB_NOT_FOUND": 404,
    "ERR_ASSET_NOT_FOUND": 404,
    "ERR_SERVICE_PLAN_NOT_FOUND": 404,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_ORDER_NOT_QUOTED": 409,
    "ERR_REVISION_NOT_RELEASED": 409,
    "ERR_FIRMWARE_NOT_CERTIFIED": 409,
    "ERR_CYCLE_TARGET_NOT_MET": 422,
    "ERR_REWORK_LIMIT_EXCEEDED": 409,
    "ERR_PARTNER_TRAINING_EXPIRED": 409,
    "ERR_PARTNER_NOT_CERTIFIED_FOR_CATEGORY": 422,
    "ERR_FIRMWARE_SUPPORT_EXPIRED": 409,
    "ERR_SUPPORT_WINDOW_ACTIVE": 409,
    "ERR_FINISH_NOT_ALLOWED": 422,
    "ERR_PLATFORM_INCOMPATIBLE": 422,
    "ERR_DUPLICATE_CERTIFICATION": 409,
    "ERR_DUPLICATE_REVISION_CODE": 409,
    "ERR_SUPERSEDE_CYCLE": 422,
    "ERR_RIG_DUTY_CLASS_UNSUPPORTED": 422,
    "ERR_ASSET_NOT_COVERED": 422,
    "ERR_FACILITY_SUSPENDED": 409,
    "ERR_ORDER_HAS_NO_LINES": 422,
    "ERR_INSTALL_JOB_ALREADY_OPEN": 409,
    "ERR_INSTALL_BLACKOUT_DAY": 422,
    "ERR_INSTALL_WINDOW_CONFLICT": 409,
    "ERR_RIG_CAPACITY_EXCEEDED": 409,
    "ERR_PARTNER_CAPACITY_EXCEEDED": 409,
    "ERR_INSUFFICIENT_PART_STOCK": 409,
    "ERR_CREDIT_LIMIT_EXCEEDED": 402,
    "ERR_INSUFFICIENT_TRADEIN_CREDIT": 402,
    "ERR_TRADEIN_CREDIT_ALREADY_APPLIED": 409,
    # non-catalogue fallback for unrouted paths
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline; aborts and rolls back."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").lower().capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)
