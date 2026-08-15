"""API error type carrying the scaffold error catalog identifiers."""


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


# Convenience constructors for the scaffold error catalog.

def unauthenticated(msg="X-User-Role header is missing or does not name a declared role"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden(msg="Role is not permitted for this endpoint or action"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def validation(msg="Malformed request"):
    return ApiError("ERR_VALIDATION", 400, msg)


def rental_item_mismatch(msg="item_type / asset-field / rate_plan combination is inconsistent"):
    return ApiError("ERR_RENTAL_ITEM_MISMATCH", 400, msg)


def stale_version(msg="Expected version does not match the entity's current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def invalid_state(msg="The entity's current state does not permit this transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)
