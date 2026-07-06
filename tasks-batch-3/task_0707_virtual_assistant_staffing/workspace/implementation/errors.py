"""Error catalog and ApiError exception (PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# (error_id -> http_status) — verbatim from PRD §5 / SCAFFOLD §1.6
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCED_ENTITY_NOT_FOUND": 422,
    "ERR_INVALID_REQUEST": 422,
    "ERR_VALIDATION_RANGE": 422,
    "ERR_PAGINATION_INVALID": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_CLIENT_NOT_ACTIVE": 409,
    "ERR_SLA_POLICY_MISSING": 409,
    "ERR_ADDON_REQUIRED": 409,
    "ERR_NOT_SPECIALIZED": 422,
    "ERR_NO_ELIGIBLE_VA": 422,
    "ERR_TASK_NOT_WORKABLE": 409,
    "ERR_CYCLE_NOT_OPEN": 409,
    "ERR_NO_OPEN_CYCLE": 409,
    "ERR_CYCLE_HAS_PENDING_ENTRIES": 409,
    "ERR_STALE_CYCLE_VERSION": 412,
    "ERR_INVOICE_VARIANT_STATE": 409,
    "ERR_NO_APPROVED_TIME": 409,
    "ERR_REPLACEMENT_INELIGIBLE": 409,
    "ERR_DUPLICATE": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
