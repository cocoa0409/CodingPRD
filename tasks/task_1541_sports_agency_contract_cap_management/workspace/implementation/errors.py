"""Error classes and error ID constants from the scaffold error catalog (1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg="Role not permitted to invoke this endpoint"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_not_found(msg="Path-scoped id does not resolve within the parent scope"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_state(msg="Target resource is in a state that does not permit the requested transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_stale_version(msg="Expected version does not match the entity's current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def err_agent_not_certified(msg="Acting agent's cert_status is not CERTIFIED"):
    return ApiError("ERR_AGENT_NOT_CERTIFIED", 422, msg)


def err_ownership_violation(msg="Acting agent does not own the resource (proposed_by / primary_agent mismatch)"):
    return ApiError("ERR_OWNERSHIP_VIOLATION", 422, msg)


def err_window_closed(msg="Outside the declared window, or end_date is not after start_date"):
    return ApiError("ERR_WINDOW_CLOSED", 422, msg)


def err_cap_would_exceed(msg="Submission would push committed + reserved + proposed_aav above luxury_threshold_cents"):
    return ApiError("ERR_CAP_WOULD_EXCEED", 422, msg)


def err_cap_hard_limit(msg="Acceptance would push committed + proposed_aav above cap_limit_cents"):
    return ApiError("ERR_CAP_HARD_LIMIT", 422, msg)


def err_resource_locked(msg="CapSeason is LOCKED/CLOSED, or Agency is SUSPENDED"):
    return ApiError("ERR_RESOURCE_LOCKED", 409, msg)


def err_duplicate_active_contract(msg="Client already has a NEGOTIATING or SIGNED Contract with the same team"):
    return ApiError("ERR_DUPLICATE_ACTIVE_CONTRACT", 409, msg)


def err_invalid_request(msg="Field constraint violation or missing required field"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_client_has_active_obligations(msg="Release attempted while a NEGOTIATING/SIGNED contract or ACTIVE endorsement exists"):
    return ApiError("ERR_CLIENT_HAS_ACTIVE_OBLIGATIONS", 409, msg)


def err_open_grievance(msg="Contract void attempted while a FILED/UNDER_REVIEW/ARBITRATION grievance is open"):
    return ApiError("ERR_OPEN_GRIEVANCE", 409, msg)
