"""Custom error type and the error catalogue (§5 of the PRD)."""


class ApiError(Exception):
    """An error carrying a machine-readable error_id and an HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


# error_id -> http status (PRD §5 / scaffold §1.6)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 422,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_PROJECT_VERSION": 412,
    "ERR_ESTIMATE_NOT_PRICED": 409,
    "ERR_EMPTY_ESTIMATE": 409,
    "ERR_SETBACK_VIOLATION": 409,
    "ERR_PERMIT_TOO_EARLY": 409,
    "ERR_MEASURE_REQUIRED": 409,
    "ERR_MATERIAL_NOT_READY": 409,
    "ERR_CREW_DOUBLE_BOOKED": 409,
    "ERR_DOCK_WINDOW_CONFLICT": 409,
    "ERR_CHANGE_ORDER_TOO_LATE": 409,
    "ERR_DRAW_GATE_NOT_MET": 409,
    "ERR_DRAW_SEQUENCE_VIOLATION": 409,
    "ERR_VALIDATION": 422,
}

_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication required: X-User-Role header missing or unknown role.",
    "ERR_FORBIDDEN": "The acting role is not permitted to perform this operation.",
    "ERR_NOT_FOUND": "A path resource does not exist.",
    "ERR_REFERENCE_NOT_FOUND": "A referenced foreign key does not resolve.",
    "ERR_INVALID_REQUEST": "A required field is missing or an enum value is out of its declared domain.",
    "ERR_INVALID_STATE": "The target resource is not in a state from which this transition is defined.",
    "ERR_STALE_PROJECT_VERSION": "expected_project_version does not match the current project version.",
    "ERR_ESTIMATE_NOT_PRICED": "The estimate must be PRICED before it can be accepted.",
    "ERR_EMPTY_ESTIMATE": "Cannot price an estimate that has no line items.",
    "ERR_SETBACK_VIOLATION": "Site measure approval blocked because setback_ok is false.",
    "ERR_PERMIT_TOO_EARLY": "Permit cannot be submitted before the project is MEASURED.",
    "ERR_MEASURE_REQUIRED": "Material order confirm requires an APPROVED site measure.",
    "ERR_MATERIAL_NOT_READY": "Crew booking confirm requires a CONFIRMED or DELIVERED material order.",
    "ERR_CREW_DOUBLE_BOOKED": "Crew booking overlaps an existing CONFIRMED booking on the same crew_id.",
    "ERR_DOCK_WINDOW_CONFLICT": "Material order delivery window conflicts with another order on the same dock_id.",
    "ERR_CHANGE_ORDER_TOO_LATE": "Change order cannot be applied at this project stage.",
    "ERR_DRAW_GATE_NOT_MET": "Draw milestone release gate is not satisfied.",
    "ERR_DRAW_SEQUENCE_VIOLATION": "FINAL draw cannot be paid before all prior non-VOIDED draws are PAID.",
    "ERR_VALIDATION": "A body field is present but semantically invalid.",
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
