"""Error classes and error-id constants.

Error IDs and HTTP statuses are taken verbatim from SCAFFOLD.yaml §1.6 and
PRD §5. Do not invent new IDs or statuses.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalog (id, http) ---
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_DUPLICATE_RESOURCE = ("ERR_DUPLICATE_RESOURCE", 409)
ERR_COMPACT_INELIGIBLE = ("ERR_COMPACT_INELIGIBLE", 422)
ERR_LICENSE_PERIOD_OVERLAP = ("ERR_LICENSE_PERIOD_OVERLAP", 409)
ERR_VISIT_SLOT_CONFLICT = ("ERR_VISIT_SLOT_CONFLICT", 409)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_DEA_EXAM_REQUIRED = ("ERR_DEA_EXAM_REQUIRED", 422)
ERR_NO_CONTROLLED_AUTHORITY = ("ERR_NO_CONTROLLED_AUTHORITY", 422)
ERR_MODALITY_NOT_PERMITTED = ("ERR_MODALITY_NOT_PERMITTED", 422)
ERR_NO_LICENSE_IN_STATE = ("ERR_NO_LICENSE_IN_STATE", 422)
ERR_STALE_PRESCRIPTION_VERSION = ("ERR_STALE_PRESCRIPTION_VERSION", 412)
ERR_PAGINATION_INVALID = ("ERR_PAGINATION_INVALID", 422)
ERR_NOT_DUE = ("ERR_NOT_DUE", 409)


def err(catalog_entry, message=None):
    error_id, http_status = catalog_entry
    return ApiError(error_id, http_status, message)
