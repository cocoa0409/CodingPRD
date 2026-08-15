"""Error type carrying the scaffold-declared error_id / message / http_status."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- Request / auth ---
def err_validation(msg="Request validation failed"):
    return ApiError("ERR_VALIDATION", msg, 400)


def err_unauthenticated(msg="Missing or invalid authentication headers"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_unauthorized_role(msg="Role is not authorized for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED_ROLE", msg, 403)


def err_forbidden_ownership(msg="Actor does not own the target resource"):
    return ApiError("ERR_FORBIDDEN_OWNERSHIP", msg, 403)


def err_juror_not_on_panel(msg="Juror is not empaneled on this award"):
    return ApiError("ERR_JUROR_NOT_ON_PANEL", msg, 403)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_stale_version(msg="Stale version: the resource has been modified"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def err_invalid_state(msg="State machine forbids this transition"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_phase(msg="Edition posture forbids this operation"):
    return ApiError("ERR_EDITION_PHASE_FORBIDDEN", msg, 409)


def err_referential(msg="Referenced entity missing or cross-edition"):
    return ApiError("ERR_REFERENTIAL_INTEGRITY", msg, 422)


def err409(error_id, msg):
    return ApiError(error_id, msg, 409)
