"""Error catalog (PRD Section 5 / SCAFFOLD 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error id -> http status (PRD 5)
ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_ASSIGNED_AGENT": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_LIVE_MONITORING_BLOCKS_CANCEL": 409,
    "ERR_911_NOT_AUTHORIZED": 409,
    "ERR_CONTRACT_NOT_MONITORING": 409,
    "ERR_ESCALATION_ORDER": 409,
    "ERR_NO_SHIFT_COVERAGE": 409,
    "ERR_SHIFT_OVERLAP": 409,
    "ERR_HOLD_OVERLAP": 409,
    "ERR_DUPLICATE": 409,
    "ERR_TEMPORAL_NOT_DUE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_ENROLL_PRECONDITION": 422,
    "ERR_CONTACT_TREE_INVALID": 422,
    "ERR_INVALID_REQUEST": 400,
}


def err(error_id, message=None):
    return ApiError(error_id, ERR[error_id], message)
