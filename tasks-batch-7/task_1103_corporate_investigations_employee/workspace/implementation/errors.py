"""Error catalog: ApiError carries error_id + http status from SCAFFOLD §1.6."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, status, message):
    return ApiError(error_id, status, message)


# --- catalog helpers (raise shortcuts) ---
def unauthenticated(msg="Missing or unknown X-User-Role / X-User-ID"):
    raise ApiError("ERR_UNAUTHENTICATED", 401, msg)


def missing_idempotency_key(msg="POST requires an Idempotency-Key header"):
    raise ApiError("ERR_MISSING_IDEMPOTENCY_KEY", 400, msg)


def idempotency_replay_mismatch(msg="Idempotency-Key replayed with a different payload"):
    raise ApiError("ERR_IDEMPOTENCY_REPLAY_MISMATCH", 409, msg)


def unauthorized_role(msg="Caller role not authorized for this endpoint or transition"):
    raise ApiError("ERR_UNAUTHORIZED_ROLE", 403, msg)


def not_found(msg="Resource not found"):
    raise ApiError("ERR_NOT_FOUND", 404, msg)


def validation(msg="Malformed field"):
    raise ApiError("ERR_VALIDATION", 400, msg)


def missing_field(field):
    raise ApiError("ERR_MISSING_REQUIRED_FIELD", 400, f"Required field missing: {field}")


def stale_version(msg="expected_case_version does not match the Case's current version"):
    raise ApiError("ERR_STALE_VERSION", 412, msg)


def invalid_state(msg="Entity is not in a state that permits this transition"):
    raise ApiError("ERR_INVALID_STATE", 409, msg)


def business(error_id, msg):
    """409/403 business errors keyed by id."""
    status = {
        "ERR_SOD_PLAN_APPROVAL": 403,
        "ERR_SOD_FINDING_FINALIZATION": 403,
        "ERR_SOD_DISCIPLINE_APPROVAL": 403,
        "ERR_SOD_REMEDIATION_VERIFICATION": 403,
        "ERR_SOD_DISCLOSURE_OVERRIDE": 403,
        "ERR_PRIVILEGED_DISTRIBUTION": 403,
    }.get(error_id, 409)
    raise ApiError(error_id, status, msg)
