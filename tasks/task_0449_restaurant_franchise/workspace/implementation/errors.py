"""Error classes and error-ID constants.

Every error_id and HTTP status here is read verbatim from SCAFFOLD §1.6 and
PRD §5 (Error Code Catalogue).
"""


class ApiError(Exception):
    """An error carrying a machine-readable error_id, message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalogue (PRD §5 / SCAFFOLD §1.6) ---
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_FRANCHISEE_NOT_APPROVED = ("ERR_FRANCHISEE_NOT_APPROVED", 409)
ERR_FRANCHISEE_HAS_OPEN_UNITS = ("ERR_FRANCHISEE_HAS_OPEN_UNITS", 409)
ERR_TERRITORY_NOT_HELD = ("ERR_TERRITORY_NOT_HELD", 409)
ERR_TERRITORY_CONFLICT = ("ERR_TERRITORY_CONFLICT", 409)
ERR_PERIOD_CLOSED = ("ERR_PERIOD_CLOSED", 409)
ERR_VENDOR_NOT_APPROVED = ("ERR_VENDOR_NOT_APPROVED", 409)
ERR_NO_SALES_BASIS = ("ERR_NO_SALES_BASIS", 409)
ERR_OUTSTANDING_OBLIGATIONS = ("ERR_OUTSTANDING_OBLIGATIONS", 409)
ERR_COMPLIANCE_BLOCK = ("ERR_COMPLIANCE_BLOCK", 409)
ERR_REMEDIATION_INCOMPLETE = ("ERR_REMEDIATION_INCOMPLETE", 409)
ERR_NO_REMEDIATION_NEEDED = ("ERR_NO_REMEDIATION_NEEDED", 409)
ERR_UNIT_NOT_OPEN = ("ERR_UNIT_NOT_OPEN", 409)
ERR_RENEWAL_WINDOW_CLOSED = ("ERR_RENEWAL_WINDOW_CLOSED", 409)
ERR_DEADLINE_NOT_PASSED = ("ERR_DEADLINE_NOT_PASSED", 409)
ERR_AUDIT_IN_PROGRESS = ("ERR_AUDIT_IN_PROGRESS", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)


def err(spec, message=None):
    """Build an ApiError from a (error_id, http_status) tuple constant."""
    return ApiError(spec[0], spec[1], message)
