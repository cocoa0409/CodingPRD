"""Domain error type and error_id -> HTTP status catalog (PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP[error_id]
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN_NOT_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_INCIDENT_NOT_ACTIVE": 409,
    "ERR_INCIDENT_NOT_DEMOBILIZING": 409,
    "ERR_INCIDENT_NOT_CLOSED": 409,
    "ERR_INCIDENT_HAS_ACTIVE_TASKS": 409,
    "ERR_TASK_NOT_READY": 409,
    "ERR_NO_DEPLOYED_RESPONDERS": 409,
    "ERR_TASK_AT_CAPACITY": 409,
    "ERR_TEAM_INACTIVE": 409,
    "ERR_CERT_REQUIREMENT_NOT_MET": 409,
    "ERR_MEMBER_DOUBLE_BOOKED": 409,
    "ERR_RESOURCE_UNAVAILABLE": 409,
    "ERR_RESOURCE_WINDOW_CONFLICT": 409,
    "ERR_DUPLICATE_CLAIM": 409,
    "ERR_STALE_VERSION": 412,
}

_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or invalid authentication headers.",
    "ERR_UNAUTHORIZED": "Role is not permitted to perform this operation.",
    "ERR_FORBIDDEN_NOT_OWNER": "Acting member does not own the target resource.",
    "ERR_NOT_FOUND": "A referenced resource does not exist.",
    "ERR_VALIDATION": "The request body is malformed.",
    "ERR_INVALID_STATE": "The resource is not in a state from which this transition is defined.",
    "ERR_INCIDENT_NOT_ACTIVE": "The parent incident is not ACTIVE.",
    "ERR_INCIDENT_NOT_DEMOBILIZING": "The incident is not DEMOBILIZING or CLOSED.",
    "ERR_INCIDENT_NOT_CLOSED": "The incident is not CLOSED.",
    "ERR_INCIDENT_HAS_ACTIVE_TASKS": "The incident still has active tasks.",
    "ERR_TASK_NOT_READY": "The referenced task is not in the required state.",
    "ERR_NO_DEPLOYED_RESPONDERS": "The task has no deployed responders.",
    "ERR_TASK_AT_CAPACITY": "The task has reached its maximum responders.",
    "ERR_TEAM_INACTIVE": "The member's team is not ACTIVE.",
    "ERR_CERT_REQUIREMENT_NOT_MET": "The member lacks a required valid certification.",
    "ERR_MEMBER_DOUBLE_BOOKED": "The member is double-booked within the rest buffer.",
    "ERR_RESOURCE_UNAVAILABLE": "The resource is out of service.",
    "ERR_RESOURCE_WINDOW_CONFLICT": "The assignment window overlaps an existing assignment.",
    "ERR_DUPLICATE_CLAIM": "A non-rejected claim already exists for this member and incident.",
    "ERR_STALE_VERSION": "The expected resource version is stale.",
}
