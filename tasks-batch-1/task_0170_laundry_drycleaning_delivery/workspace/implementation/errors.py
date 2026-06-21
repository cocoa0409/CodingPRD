"""Error catalogue (PRD §5). Each error carries an error_id and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# (error_id -> http status), straight from PRD §5 error catalogue.
ERROR_STATUS = {
    # auth
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    # request validation
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_INTERVAL": 400,
    "ERR_SERVICE_TYPE_FIELD_MISMATCH": 422,
    "ERR_CLAIM_SUBJECT_MISMATCH": 422,
    # not found
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_SUBSCRIPTION_NOT_FOUND": 404,
    "ERR_WINDOW_NOT_FOUND": 404,
    "ERR_LOCKER_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_GARMENT_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    # order state
    "ERR_INVALID_ORDER_STATE": 409,
    "ERR_NO_GARMENTS": 409,
    "ERR_ORDER_NOT_PICKED_UP": 409,
    "ERR_GARMENTS_NOT_LOGGED": 409,
    "ERR_GARMENTS_NOT_CLEANED": 409,
    "ERR_NO_REWORK_REQUESTED": 409,
    "ERR_DELIVERY_BEFORE_READY": 409,
    "ERR_NO_LOCKER_ASSIGNED": 409,
    # garment state
    "ERR_GARMENT_NOT_CLEANING": 409,
    "ERR_GARMENT_NOT_CLEANED": 409,
    "ERR_GARMENT_NOT_LOSABLE": 409,
    "ERR_INVALID_INTAKE_MEASUREMENT": 422,
    # claim state
    "ERR_INVALID_CLAIM_STATE": 409,
    "ERR_CLAIM_GARMENT_NOT_LOST": 409,
    "ERR_APPEAL_LIMIT_REACHED": 409,
    "ERR_APPEAL_LIMIT_NOT_REACHED": 409,
    # subscription state
    "ERR_INVALID_SUBSCRIPTION_STATE": 409,
    # locker / assignment state
    "ERR_INVALID_ASSIGNMENT_STATE": 409,
    "ERR_LOCKER_COMPARTMENT_CONFLICT": 409,
    "ERR_HOLD_NOT_EXPIRED": 409,
    # window / capacity
    "ERR_WINDOW_ZONE_MISMATCH": 409,
    "ERR_WINDOW_FULL": 409,
    # customer safety
    "ERR_CUSTOMER_BLOCKED": 403,
    # OCC
    "ERR_STALE_ORDER_VERSION": 412,
    "ERR_STALE_SUBSCRIPTION_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
