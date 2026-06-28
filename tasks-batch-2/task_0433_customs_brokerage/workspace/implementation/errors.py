"""Error classes and error-id constants.

Error ids and HTTP statuses are taken verbatim from the PRD §5 / scaffold §1.6
error catalog.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error id -> http status (PRD §5 Error Code Catalogue)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_STATE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_BOND_IMPORTER_MISMATCH": 422,
    "ERR_PGA_NOT_CLEARED": 409,
    "ERR_ISF_NOT_FILED": 409,
    "ERR_ISF_INCOMPLETE": 422,
    "ERR_ENTRY_PRECEDES_MANIFEST": 422,
    "ERR_INVALID_FORMAT": 422,
    "ERR_DUPLICATE": 409,
    "ERR_BOND_INSUFFICIENT": 422,
    "ERR_BOND_SATURATED": 409,
    "ERR_STALE_ENTRY_VERSION": 412,
    "ERR_VALIDATION": 422,
    "ERR_NO_LINES": 422,
    "ERR_INVALID_EXAM_WINDOW": 422,
    "ERR_EXAM_SLOT_OVERLAP": 409,
    "ERR_STATEMENT_PERIOD_OVERLAP": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
