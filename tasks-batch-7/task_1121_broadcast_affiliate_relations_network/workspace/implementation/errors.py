"""Error classes and error ID constants per PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Error IDs per PRD §5 / SCAFFOLD errors table
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"           # 401
ERR_UNAUTHORIZED_ROLE = "ERR_UNAUTHORIZED_ROLE"       # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                       # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_NETWORK_LOCKDOWN = "ERR_NETWORK_LOCKDOWN"         # 409
ERR_SOD_VIOLATION = "ERR_SOD_VIOLATION"               # 403
ERR_RATE_SUM_MISMATCH = "ERR_RATE_SUM_MISMATCH"       # 422
ERR_INVALID_TIME_RANGE = "ERR_INVALID_TIME_RANGE"     # 422
ERR_AVAIL_POOL_EXHAUSTED = "ERR_AVAIL_POOL_EXHAUSTED" # 409
ERR_NO_WINDOW_OVERLAP = "ERR_NO_WINDOW_OVERLAP"       # 422
ERR_TERRITORY_EXCLUSIVITY_HELD = "ERR_TERRITORY_EXCLUSIVITY_HELD"  # 409
ERR_PREEMPTION_QUOTA_EXCEEDED = "ERR_PREEMPTION_QUOTA_EXCEEDED"    # 422
ERR_DUPLICATE_COMMITTED_SETTLEMENT = "ERR_DUPLICATE_COMMITTED_SETTLEMENT"  # 409
ERR_CLAIMANT_NOT_HOLDER = "ERR_CLAIMANT_NOT_HOLDER"   # 422
ERR_STALE_AGREEMENT_VERSION = "ERR_STALE_AGREEMENT_VERSION"  # 412
ERR_STALE_STATION_VERSION = "ERR_STALE_STATION_VERSION"      # 412
ERR_COUNTER_ROUND_EXHAUSTED = "ERR_COUNTER_ROUND_EXHAUSTED"  # 409
ERR_FUTURE_OUTAGE = "ERR_FUTURE_OUTAGE"               # 422
ERR_INVALID_TERM_LENGTH = "ERR_INVALID_TERM_LENGTH"   # 422
ERR_FUTURE_PERIOD = "ERR_FUTURE_PERIOD"               # 422
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"           # 400
ERR_DEFICIENT_CLEARANCE = "ERR_DEFICIENT_CLEARANCE"   # 409
ERR_STALE_VERSION_GENERIC = "ERR_STALE_VERSION_GENERIC"      # 412 (unused)


def err_unauthenticated(msg="Missing or invalid X-User-Role / X-User-ID headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def err_unauthorized_role(msg="Role not authorized for this endpoint"):
    return ApiError(ERR_UNAUTHORIZED_ROLE, 403, msg)


def err_not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def err_invalid_state(msg="Invalid state for requested transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def err_invalid_request(msg="Malformed payload or missing required field"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def err_rate_sum_mismatch(msg="reverse_comp_pct + retrans_share_pct must equal 1.0"):
    return ApiError(ERR_RATE_SUM_MISMATCH, 422, msg)


def err_invalid_time_range(msg="End time must be strictly greater than start time"):
    return ApiError(ERR_INVALID_TIME_RANGE, 422, msg)


def err_future_period(msg="period_index must not exceed network current_period_index"):
    return ApiError(ERR_FUTURE_PERIOD, 422, msg)


def err_future_outage(msg="OutageEvent.ended_at_utc must not exceed Network.current_utc"):
    return ApiError(ERR_FUTURE_OUTAGE, 422, msg)


def err_invalid_term_length(msg="proposed_term_months must be in {12, 24, 36, 48, 60}"):
    return ApiError(ERR_INVALID_TERM_LENGTH, 422, msg)
