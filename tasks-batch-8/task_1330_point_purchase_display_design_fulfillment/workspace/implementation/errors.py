"""Error classes with the scaffold's exact error IDs and HTTP statuses."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(message="Missing or invalid X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, message)


def err_unauthorized(message="Role not permitted for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED", 403, message)


def err_not_found(message="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, message)


def err_invalid_state(message="Resource is not in a state that permits the requested transition"):
    return ApiError("ERR_INVALID_STATE", 409, message)


def err_stale_version(message="expected version does not match the parent's current version"):
    return ApiError("ERR_STALE_VERSION", 412, message)


def err_compliance_failed(message="Design fails active compliance rules, or program lacks an active compliance rule"):
    return ApiError("ERR_COMPLIANCE_FAILED", 422, message)


def err_duplicate(message="Uniqueness violation"):
    return ApiError("ERR_DUPLICATE", 409, message)


def err_window_violation(message="Appointment outside ship window, ship before window start, or deliver after window end + 7d grace"):
    return ApiError("ERR_WINDOW_VIOLATION", 422, message)


def err_referential(message="Cross-entity reference invalid"):
    return ApiError("ERR_REFERENTIAL", 422, message)


def err_invalid_request(message="Field-level validation failure"):
    return ApiError("ERR_INVALID_REQUEST", 400, message)
