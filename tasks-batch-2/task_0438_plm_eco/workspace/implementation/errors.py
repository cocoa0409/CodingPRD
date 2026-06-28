"""Error classes and the error catalogue (PRD Section 5).

Every error_id and its HTTP status is taken verbatim from the PRD error
code catalogue and the scaffold error table.
"""


class ApiError(Exception):
    """A domain error carrying a machine-readable error_id and HTTP status.

    The error body uses the exact field names from the response envelope:
    data.error_id and data.message (PRD Section 2.2).
    """

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalogue (PRD Section 5 / scaffold Table 6) -----------------------
# Maps error_id -> http status.
ERROR_STATUS = {
    "ERR_MISSING_AUTH_HEADER": 401,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_BOM_CYCLE": 409,
    "ERR_EMPTY_BOM": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_TASK_ASSIGNEE": 403,
    "ERR_NO_AFFECTED_ITEMS": 409,
    "ERR_INSUFFICIENT_APPROVERS": 409,
    "ERR_ECR_NOT_APPROVED": 409,
    "ERR_ECO_NOT_APPROVED": 409,
    "ERR_NO_GOVERNING_ECO": 409,
    "ERR_REVISION_ALREADY_GOVERNED": 409,
    "ERR_NOT_YET_EFFECTIVE": 409,
    "ERR_DEVIATION_WINDOW_OVERLAP": 409,
    "ERR_INVALID_WINDOW": 422,
    "ERR_NOT_YET_EXPIRED": 409,
    "ERR_PART_NOT_BUY": 409,
    "ERR_PART_NOT_RELEASED": 409,
    "ERR_REVISION_NOT_RELEASED": 409,
    "ERR_UNIT_NONCONFORMING": 409,
    "ERR_VALIDATION": 422,
}


def err(error_id, message=None):
    """Construct an ApiError, looking the http status up from the catalogue."""
    return ApiError(error_id, ERROR_STATUS[error_id], message)
