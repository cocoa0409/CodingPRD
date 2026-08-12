"""Error catalog for the Home Dialysis Supply Logistics API."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- auth ---
def err_missing_headers():
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                    "X-User-ID or X-User-Role header missing/empty")


def err_insufficient_permissions():
    return ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403,
                    "Role not permitted on this endpoint")


def err_forbidden_ownership():
    return ApiError("ERR_FORBIDDEN_OWNERSHIP", 403,
                    "Patient-role caller's X-User-ID does not match the target patient")


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_request(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_effective_range(msg="Invalid effective range"):
    return ApiError("ERR_INVALID_EFFECTIVE_RANGE", 400, msg)


def err_stale_version():
    return ApiError("ERR_STALE_VERSION", 412,
                    "expected version does not match current version")


def err_patient_invalid_state():
    return ApiError("ERR_PATIENT_INVALID_STATE", 409,
                    "Patient lifecycle action not available from current state")
