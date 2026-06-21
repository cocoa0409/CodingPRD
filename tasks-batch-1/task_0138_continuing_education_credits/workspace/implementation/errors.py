"""Error classes and the error catalog (PRD §5 / SCAFFOLD §1.6).

Every error carries an error_id, a human-readable message, and an HTTP status.
The error_id strings and HTTP statuses are taken verbatim from the scaffold's
error catalog — do not rename or remap.
"""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# ─── Error catalog: error_id -> http_status (PRD §5) ──────────────────
ERROR_HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_STATE": 409,
    "ERR_PROVIDER_NOT_ACCREDITED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_COMPLETION_OUT_OF_WINDOW": 422,
    "ERR_CYCLE_OVERLAP": 409,
    "ERR_AUDIT_COOLDOWN_ACTIVE": 409,
    "ERR_AUDIT_ALREADY_OPEN": 409,
    "ERR_SAME_JURISDICTION": 422,
    "ERR_REQUIREMENTS_NOT_MET": 409,
    "ERR_CARRYOVER_EXCEEDS_CAP": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_REQUEST": 400,
    "ERR_VALIDATION_RANGE": 422,
}


def _make(error_id):
    status = ERROR_HTTP_STATUS[error_id]

    def factory(message=None):
        return ApiError(error_id, message or error_id, status)

    return factory


# Convenience constructors
unauthenticated = _make("ERR_UNAUTHENTICATED")
forbidden = _make("ERR_FORBIDDEN")
not_found = _make("ERR_NOT_FOUND")
not_resource_owner = _make("ERR_NOT_RESOURCE_OWNER")
invalid_state = _make("ERR_INVALID_STATE")
provider_not_accredited = _make("ERR_PROVIDER_NOT_ACCREDITED")
segregation_of_duties = _make("ERR_SEGREGATION_OF_DUTIES")
completion_out_of_window = _make("ERR_COMPLETION_OUT_OF_WINDOW")
cycle_overlap = _make("ERR_CYCLE_OVERLAP")
audit_cooldown_active = _make("ERR_AUDIT_COOLDOWN_ACTIVE")
audit_already_open = _make("ERR_AUDIT_ALREADY_OPEN")
same_jurisdiction = _make("ERR_SAME_JURISDICTION")
requirements_not_met = _make("ERR_REQUIREMENTS_NOT_MET")
carryover_exceeds_cap = _make("ERR_CARRYOVER_EXCEEDS_CAP")
stale_version = _make("ERR_STALE_VERSION")
invalid_request = _make("ERR_INVALID_REQUEST")
validation_range = _make("ERR_VALIDATION_RANGE")
