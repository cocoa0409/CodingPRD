"""Error type carrying the scaffold's error_id + HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- auth / shape ---
def err_bad_context(msg="X-User-ID or X-User-Role header missing or role undeclared"):
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400, msg)


def err_forbidden(msg="Role not permitted on this endpoint"):
    return ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, msg)


def err_sod(msg="Adjudicator may not adjudicate a claim they submitted"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


def err_invalid(msg="Malformed or invalid request"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_not_found(resource, msg=None):
    return ApiError(f"ERR_{resource}_NOT_FOUND", 404,
                    msg or f"{resource} id does not exist")


def err_stale(msg="expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)
