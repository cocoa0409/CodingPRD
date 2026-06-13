"""Error catalog and the ApiError exception type.

Every error_id / http_status pair is taken verbatim from PRD §5 and
SCAFFOLD §1.6. Do not invent codes.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalog (PRD §5 / SCAFFOLD §1.6) ---------------------------------
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_VALIDATION = ("ERR_VALIDATION", 400)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_ENUM = ("ERR_INVALID_ENUM", 422)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_IDENTITY_NOT_ACTIVE = ("ERR_IDENTITY_NOT_ACTIVE", 409)
ERR_ROLE_RETIRED = ("ERR_ROLE_RETIRED", 409)
ERR_ENTITLEMENT_ARCHIVED = ("ERR_ENTITLEMENT_ARCHIVED", 409)
ERR_SOD_SELF_ACTION = ("ERR_SOD_SELF_ACTION", 403)
ERR_DUAL_APPROVAL_REQUIRED = ("ERR_DUAL_APPROVAL_REQUIRED", 422)
ERR_SOD_CONFLICT = ("ERR_SOD_CONFLICT", 409)
ERR_SOD_OVERRIDE_REQUIRED = ("ERR_SOD_OVERRIDE_REQUIRED", 422)
ERR_JIT_WINDOW_OVERLAP = ("ERR_JIT_WINDOW_OVERLAP", 409)
ERR_CAMPAIGN_NOT_ACTIVE = ("ERR_CAMPAIGN_NOT_ACTIVE", 409)
ERR_CAMPAIGN_WINDOW_OVERLAP = ("ERR_CAMPAIGN_WINDOW_OVERLAP", 409)
ERR_IDENTITY_HAS_ACTIVE_GRANTS = ("ERR_IDENTITY_HAS_ACTIVE_GRANTS", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_SOD_PAIR_INVALID = ("ERR_SOD_PAIR_INVALID", 422)


def err(catalog_entry, message=None):
    error_id, http_status = catalog_entry
    return ApiError(error_id, http_status, message)
