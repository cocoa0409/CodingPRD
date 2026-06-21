"""Error classes and error ID constants (PRD section 5 / scaffold 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue (verbatim from PRD section 5 / scaffold 1.6)
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_FK_NOT_FOUND = ("ERR_FK_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_SEGREGATION_OF_DUTIES = ("ERR_SEGREGATION_OF_DUTIES", 403)
ERR_DEVIATION_REQUIRED = ("ERR_DEVIATION_REQUIRED", 409)
ERR_DISPOSITION_NOT_ALLOWED = ("ERR_DISPOSITION_NOT_ALLOWED", 409)
ERR_DEVIATION_OVERLAP = ("ERR_DEVIATION_OVERLAP", 409)
ERR_DEVIATION_IN_USE = ("ERR_DEVIATION_IN_USE", 409)
ERR_AUDITOR_DOUBLE_BOOKED = ("ERR_AUDITOR_DOUBLE_BOOKED", 409)
ERR_AUDIT_HAS_OPEN_FINDINGS = ("ERR_AUDIT_HAS_OPEN_FINDINGS", 409)
ERR_FINDING_NCR_OPEN = ("ERR_FINDING_NCR_OPEN", 409)
ERR_FINDING_REQUIRES_NCR = ("ERR_FINDING_REQUIRES_NCR", 409)
ERR_REVISION_SEQUENCE = ("ERR_REVISION_SEQUENCE", 409)
ERR_EFFECTIVENESS_TOO_LOW = ("ERR_EFFECTIVENESS_TOO_LOW", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_NCR_HAS_CAPA = ("ERR_NCR_HAS_CAPA", 409)


def err(catalog_entry, message=None):
    """Build an ApiError from a (id, http_status) catalog tuple."""
    error_id, http_status = catalog_entry
    return ApiError(error_id, http_status, message)
