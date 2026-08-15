"""Custom exception carrying error_id, message, and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Convenience constructors -------------------------------------------------

def unauthenticated(msg="Missing or malformed authentication headers"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def unauthorized(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED", msg, 403)


def not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def invalid_state(msg="Invalid state for requested transition"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def posture_gated(msg="WatchGroup posture does not permit this operation"):
    return ApiError("ERR_POSTURE_GATED", msg, 409)


def segregation(msg="Segregation of duties violation"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", msg, 403)


def quiet_hours(msg="Scheduled send falls inside quiet hours"):
    return ApiError("ERR_QUIET_HOURS", msg, 422)


def room_slot_conflict(msg="Room slot overlaps another meeting in the same precinct"):
    return ApiError("ERR_ROOM_SLOT_CONFLICT", msg, 409)


def closure_conflict(msg="Street-closure window conflicts with another approved event"):
    return ApiError("ERR_CLOSURE_CONFLICT", msg, 409)


def training_cooldown(msg="Training session precedes group cooldown"):
    return ApiError("ERR_TRAINING_COOLDOWN", msg, 422)


def referential(msg="Referential integrity violation"):
    return ApiError("ERR_REFERENTIAL_INTEGRITY", msg, 422)


def constraint_violation(msg="Uniqueness or cardinality constraint violated"):
    return ApiError("ERR_CONSTRAINT_VIOLATION", msg, 409)


def invalid_request(msg="Field-level validation failure"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def inventory_limit(msg="Inventory conservation violated"):
    return ApiError("ERR_INVENTORY_LIMIT", msg, 422)


def stale_version(msg="Optimistic concurrency mismatch"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def data_share_required(msg="Operation requires an ACTIVE DataShareAgreement"):
    return ApiError("ERR_DATA_SHARE_REQUIRED", msg, 409)


def certification_required(msg="Operation requires a stronger certification"):
    return ApiError("ERR_CERTIFICATION_REQUIRED", msg, 409)


def no_active_captain(msg="Block requires exactly one ACTIVE captain assignment"):
    return ApiError("ERR_NO_ACTIVE_CAPTAIN", msg, 409)


def reporter_only(msg="Only the original reporter may resubmit"):
    return ApiError("ERR_REPORTER_ONLY", msg, 403)


def duplicate(msg="A PENDING or CONDITIONAL review already exists for this group"):
    return ApiError("ERR_DUPLICATE", msg, 409)
