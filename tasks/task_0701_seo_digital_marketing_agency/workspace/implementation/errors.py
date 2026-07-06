"""Error catalog and custom exception type."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http_status (PRD §5)
ERROR_CATALOG = {
    "ERR_MISSING_AUTH": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_RETAINER_VERSION": 412,
    "ERR_RETAINER_NOT_ACTIVE": 409,
    "ERR_RETAINER_NOT_SIGNABLE": 409,
    "ERR_CLIENT_NOT_AUDITED": 409,
    "ERR_CONTRACT_STILL_BINDING": 409,
    "ERR_CAMPAIGN_HAS_OPEN_DISPUTE": 409,
    "ERR_DISPUTE_EXCEEDS_SPEND": 409,
    "ERR_BUDGET_EXCEEDED": 409,
    "ERR_OPTIMIZATION_THRESHOLD_NOT_MET": 409,
    "ERR_SPRINT_HAS_OPEN_WORK": 409,
    "ERR_INVALID_SPRINT_WINDOW": 422,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_SPRINT_CAPACITY_EXCEEDED": 409,
    "ERR_INSUFFICIENT_CREDITS": 409,
    "ERR_SPRINT_WINDOW_OVERLAP": 409,
    "ERR_REPORT_PERIOD_OVERLAP": 409,
}


def err(error_id, message=None):
    """Construct an ApiError using the catalog's HTTP status."""
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
