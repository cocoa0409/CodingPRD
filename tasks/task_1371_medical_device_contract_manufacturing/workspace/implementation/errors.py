"""Error type carrying the catalog error_id, HTTP status, and message."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- auth ---
def err_user_context():
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                    "X-User-ID and X-User-Role headers must be present and the role must be recognized")


def err_forbidden_role():
    return ApiError("ERR_FORBIDDEN_ROLE", 403, "Role is not permitted for this endpoint")


def err_sod():
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                    "The acting operator may not approve/close a record they authored or executed")


# --- shape / existence / concurrency ---
def err_validation(msg="Request body failed validation"):
    return ApiError("ERR_VALIDATION", 400, msg)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_stale_version():
    return ApiError("ERR_STALE_VERSION", 412,
                    "expected version does not match the parent's current version")


def err_clock_regression():
    return ApiError("ERR_CLOCK_REGRESSION", 400,
                    "The logical clock may only move forward to a valid UTC ISO 8601 instant")


def err_udi_check():
    return ApiError("ERR_UDI_CHECK_DIGIT_MISMATCH", 400,
                    "udi_di final digit does not satisfy the GS1 check digit over the first 13 digits")


# --- state machine ---
def err_state(msg="Trigger is not a declared transition from the entity's current state"):
    return ApiError("ERR_INVALID_STATE_TRANSITION", 409, msg)
