"""Error catalogue (PRD section 5) and the exception used to raise them."""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_ACTION_ROLE_MISMATCH": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CARRIER_NOT_FOUND": 404,
    "ERR_NPA_NOT_FOUND": 404,
    "ERR_RATE_CENTER_NOT_FOUND": 404,
    "ERR_BLOCK_NOT_FOUND": 404,
    "ERR_ALLOCATION_REQUEST_NOT_FOUND": 404,
    "ERR_FILING_NOT_FOUND": 404,
    "ERR_AUDIT_FINDING_NOT_FOUND": 404,
    "ERR_RECLAMATION_ORDER_NOT_FOUND": 404,
    "ERR_RELIEF_PLAN_NOT_FOUND": 404,
    "ERR_PORT_REQUEST_NOT_FOUND": 404,
    "ERR_STALE_RATE_CENTER_VERSION": 412,
    "ERR_STALE_BLOCK_VERSION": 412,
    "ERR_TERMINAL_STATE": 409,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_INFO_CYCLE_LIMIT_REACHED": 409,
    "ERR_CARRIER_NOT_ELIGIBLE": 422,
    "ERR_LICENSE_EXPIRED": 422,
    "ERR_CARRIER_ON_PROBATION": 422,
    "ERR_JURISDICTION_MISMATCH": 422,
    "ERR_NUMBER_OUTSIDE_BLOCK": 422,
    "ERR_PORT_BLOCK_NOT_ROUTED": 409,
    "ERR_ROUTING_INTERVAL_OVERLAP": 409,
    "ERR_RELIEF_WINDOW_OVERLAP": 409,
    "ERR_COMMENT_WINDOW_CLOSED": 409,
    "ERR_ACTIVATION_WINDOW_EXPIRED": 409,
    "ERR_DUPLICATE_OCN": 409,
    "ERR_DUPLICATE_NPA_CODE": 409,
    "ERR_DUPLICATE_BLOCK_LABEL": 409,
    "ERR_DUPLICATE_FILING_PERIOD": 409,
    "ERR_RATE_CENTER_NOT_ACCEPTING_INITIAL": 409,
    "ERR_BLOCK_NOT_POOLING_ELIGIBLE": 422,
    "ERR_UTILIZATION_FILING_REQUIRED": 422,
    "ERR_UTILIZATION_THRESHOLD_NOT_MET": 422,
    "ERR_EXHAUST_HORIZON_TOO_LONG": 422,
    "ERR_SAFETY_VALVE_LIMIT_EXCEEDED": 422,
    "ERR_POOL_INSUFFICIENT_BLOCKS": 409,
    "ERR_GRANT_EXCEEDS_ENTITLEMENT": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return words.capitalize()


def fail(error_id, message=None):
    raise ApiError(error_id, message)
