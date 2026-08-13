"""Error type carrying the scaffold-defined error_id / http_status pair."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- auth / request shape -------------------------------------------------
def err_missing_context():
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                    "X-User-ID and X-User-Role headers are required and role must be a declared role name")


def err_forbidden_role():
    return ApiError("ERR_FORBIDDEN_ROLE", 403, "Caller role is not permitted for this operation")


def err_ownership():
    return ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Self-service caller may only act on their own records")


def err_sod():
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                    "Caller may not certify/approve work they performed themselves")


def err_invalid_request(msg="Request failed shape validation"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_stale_version():
    return ApiError("ERR_STALE_VERSION", 412, "expected version does not match the entity's current version")


# --- not found ------------------------------------------------------------
_NOT_FOUND = {
    "volunteer": "ERR_VOLUNTEER_NOT_FOUND",
    "certification": "ERR_CERTIFICATION_NOT_FOUND",
    "season": "ERR_SEASON_NOT_FOUND",
    "bed": "ERR_BED_NOT_FOUND",
    "crop_plan": "ERR_CROP_PLAN_NOT_FOUND",
    "slot": "ERR_SHIFT_SLOT_NOT_FOUND",
    "signup": "ERR_SIGNUP_NOT_FOUND",
    "booking": "ERR_GROUP_BOOKING_NOT_FOUND",
    "key": "ERR_SHED_KEY_NOT_FOUND",
    "tool": "ERR_TOOL_NOT_FOUND",
    "checkout": "ERR_TOOL_CHECKOUT_NOT_FOUND",
    "harvest": "ERR_HARVEST_LOG_NOT_FOUND",
    "recipient": "ERR_RECIPIENT_NOT_FOUND",
    "allocation": "ERR_ALLOCATION_NOT_FOUND",
    "irrigation": "ERR_IRRIGATION_SCHEDULE_NOT_FOUND",
}


def err_not_found(kind: str):
    return ApiError(_NOT_FOUND[kind], 404, f"{kind} does not exist")


def err_state(kind: str):
    return ApiError(f"ERR_INVALID_{kind}_STATE", 409, f"{kind} is not in a state accepting this transition")


def err(error_id: str, msg: str = ""):
    """Generic 409 helper for catalog errors."""
    return ApiError(error_id, 409, msg or error_id)
