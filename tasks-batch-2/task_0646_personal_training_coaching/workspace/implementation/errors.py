"""Error classes and error-id constants (PRD §5 / scaffold §1.6)."""


class ApiError(Exception):
    """An application error carrying the scaffold's error_id, message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- auth ---
ERR_MISSING_AUTH = "ERR_MISSING_AUTH"                              # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"                          # 403
# --- existence ---
ERR_TRAINER_NOT_FOUND = "ERR_TRAINER_NOT_FOUND"                    # 404
ERR_CLIENT_NOT_FOUND = "ERR_CLIENT_NOT_FOUND"                      # 404
ERR_ENGAGEMENT_NOT_FOUND = "ERR_ENGAGEMENT_NOT_FOUND"              # 404
ERR_PACK_NOT_FOUND = "ERR_PACK_NOT_FOUND"                          # 404
ERR_BOOKING_NOT_FOUND = "ERR_BOOKING_NOT_FOUND"                    # 404
ERR_PROGRAM_NOT_FOUND = "ERR_PROGRAM_NOT_FOUND"                    # 404
ERR_MACROPLAN_NOT_FOUND = "ERR_MACROPLAN_NOT_FOUND"                # 404
ERR_CHECKIN_NOT_FOUND = "ERR_CHECKIN_NOT_FOUND"                    # 404
# --- request validation ---
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                        # 422
# --- state ---
ERR_INVALID_STATE = "ERR_INVALID_STATE"                            # 409
ERR_INTAKE_NOT_SUBMITTED = "ERR_INTAKE_NOT_SUBMITTED"              # 409
ERR_INTAKE_NOT_ASSESSED = "ERR_INTAKE_NOT_ASSESSED"                # 409
ERR_ENGAGEMENT_NOT_ACTIVE = "ERR_ENGAGEMENT_NOT_ACTIVE"            # 409
ERR_PROGRAM_NOT_PUBLISHED = "ERR_PROGRAM_NOT_PUBLISHED"            # 409
# --- business referential / constraint ---
ERR_PACK_MODEL_MISMATCH = "ERR_PACK_MODEL_MISMATCH"                # 409
ERR_NO_SESSIONS_REMAINING = "ERR_NO_SESSIONS_REMAINING"            # 409
ERR_NO_WEIGHT_FOR_MACROS = "ERR_NO_WEIGHT_FOR_MACROS"             # 409
# --- safety / threshold ---
ERR_BOOKING_PRIVILEGE_SUSPENDED = "ERR_BOOKING_PRIVILEGE_SUSPENDED"  # 403
# --- temporal ---
ERR_BOOKING_OVERLAP = "ERR_BOOKING_OVERLAP"                        # 409
ERR_CLIENT_DOUBLE_BOOKED = "ERR_CLIENT_DOUBLE_BOOKED"              # 409
ERR_RESCHEDULE_TOO_LATE = "ERR_RESCHEDULE_TOO_LATE"                # 409
ERR_SESSION_NOT_STARTED = "ERR_SESSION_NOT_STARTED"                # 409
ERR_SESSION_NOT_ENDED = "ERR_SESSION_NOT_ENDED"                    # 409
# --- concurrency ---
ERR_STALE_VERSION = "ERR_STALE_VERSION"                            # 412


def missing_auth(msg="X-User-ID or X-User-Role header missing or malformed"):
    return ApiError(ERR_MISSING_AUTH, 401, msg)


def forbidden_role(msg="Role not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_found(error_id, msg=None):
    return ApiError(error_id, 404, msg or "Resource not found")


def invalid_request(msg="Invalid request body"):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def invalid_state(error_id=ERR_INVALID_STATE, msg=None):
    return ApiError(error_id, 409, msg or "Resource is not in the required state")


def stale_version(msg="Expected version does not match current version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)
