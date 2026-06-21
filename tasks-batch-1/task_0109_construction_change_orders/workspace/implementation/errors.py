"""Error catalogue (PRD §5 / scaffold §1.6).

Each error carries an error_id (machine-readable) and an HTTP status. The error
response body uses {error_id, message} per the response envelope.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status per error_id (PRD §5 catalogue).
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_CROSS_PROJECT_REFERENCE = ("ERR_CROSS_PROJECT_REFERENCE", 422)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_SEGREGATION_OF_DUTIES = ("ERR_SEGREGATION_OF_DUTIES", 409)
ERR_NONSEQUENTIAL_APPLICATION = ("ERR_NONSEQUENTIAL_APPLICATION", 422)
ERR_BILLING_PERIOD_OVERLAP = ("ERR_BILLING_PERIOD_OVERLAP", 409)
ERR_INSPECTION_BUFFER_CONFLICT = ("ERR_INSPECTION_BUFFER_CONFLICT", 409)
ERR_DUPLICATE_ITEM_NO = ("ERR_DUPLICATE_ITEM_NO", 409)
ERR_LINE_EDITS_UNBALANCED = ("ERR_LINE_EDITS_UNBALANCED", 422)
ERR_OVERBILLING = ("ERR_OVERBILLING", 422)
ERR_RELEASE_EXCEEDS_HELD = ("ERR_RELEASE_EXCEEDS_HELD", 422)
ERR_WAIVER_MISMATCH = ("ERR_WAIVER_MISMATCH", 422)
ERR_PAYAPP_NOT_CERTIFIED = ("ERR_PAYAPP_NOT_CERTIFIED", 409)
ERR_STALE_PROJECT_VERSION = ("ERR_STALE_PROJECT_VERSION", 412)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)


def err(spec, message=None):
    """Build an ApiError from a (error_id, http_status) tuple constant."""
    error_id, http_status = spec
    return ApiError(error_id, http_status, message)
