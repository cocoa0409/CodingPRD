"""Error classes and error ID constants for the Equipment Maintenance API."""


class APIError(Exception):
    """A structured API error carrying error_id, message, http_status."""

    def __init__(self, error_id: str, message: str, http_status: int):
        self.error_id = error_id
        self.message = message
        self.http_status = http_status
        super().__init__(message)


# Error ID constants pulled directly from SCAFFOLD §1.6.
ERR_BAD_REQUEST = ("ERR_BAD_REQUEST", 400)
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_FORBIDDEN_NOT_OWNER = ("ERR_FORBIDDEN_NOT_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_VERSION_CONFLICT = ("ERR_VERSION_CONFLICT", 409)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_EQUIPMENT_LIFECYCLE = ("ERR_EQUIPMENT_LIFECYCLE", 409)
ERR_EQUIPMENT_BUSY = ("ERR_EQUIPMENT_BUSY", 409)
ERR_NO_ACTIVE_PLAN = ("ERR_NO_ACTIVE_PLAN", 409)
ERR_PAUSE_TOO_FRESH = ("ERR_PAUSE_TOO_FRESH", 409)
ERR_REQUISITIONS_PENDING = ("ERR_REQUISITIONS_PENDING", 409)
ERR_PARTS_NOT_ISSUED = ("ERR_PARTS_NOT_ISSUED", 409)
ERR_INSUFFICIENT_STOCK = ("ERR_INSUFFICIENT_STOCK", 409)
ERR_INSUFFICIENT_AVAILABLE = ("ERR_INSUFFICIENT_AVAILABLE", 409)
ERR_PLAN_KIND_FIELDS = ("ERR_PLAN_KIND_FIELDS", 422)
ERR_CROSS_SITE_REFERENCE = ("ERR_CROSS_SITE_REFERENCE", 422)
ERR_EVIDENCE_MISSING = ("ERR_EVIDENCE_MISSING", 422)
ERR_SKILL_MISMATCH = ("ERR_SKILL_MISMATCH", 422)
ERR_RETURN_QTY_INVALID = ("ERR_RETURN_QTY_INVALID", 422)
ERR_TEMPORAL_INVALID = ("ERR_TEMPORAL_INVALID", 422)


def raise_err(err_tuple, message: str = ""):
    eid, http = err_tuple
    raise APIError(eid, message or eid, http)
