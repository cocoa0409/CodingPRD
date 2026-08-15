"""Error catalog (SCAFFOLD §1.6 / PRD §5). Each error carries its exact id and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                        # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"            # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"                # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                # 412
ERR_COACH_NOT_CREDENTIALED = "ERR_COACH_NOT_CREDENTIALED"  # 422
ERR_FIT_NOT_ESTABLISHED = "ERR_FIT_NOT_ESTABLISHED"    # 422
ERR_SESSION_OVERLAP = "ERR_SESSION_OVERLAP"            # 409
ERR_DISCOVERY_CALL_OVERLAP = "ERR_DISCOVERY_CALL_OVERLAP"  # 409
ERR_OUTSIDE_PROGRAM_WINDOW = "ERR_OUTSIDE_PROGRAM_WINDOW"  # 422
ERR_RESCHEDULE_CAP_REACHED = "ERR_RESCHEDULE_CAP_REACHED"  # 422
ERR_NO_SESSIONS_REMAINING = "ERR_NO_SESSIONS_REMAINING"    # 422
ERR_COACH_CAPACITY_FULL = "ERR_COACH_CAPACITY_FULL"    # 422
ERR_COHORT_NOT_JOINABLE = "ERR_COHORT_NOT_JOINABLE"    # 409
ERR_DUPLICATE_RESOURCE = "ERR_DUPLICATE_RESOURCE"      # 409
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"    # 422
ERR_TIER_RETIRED = "ERR_TIER_RETIRED"                  # 422
ERR_PAYMENT_PLAN_INVALID = "ERR_PAYMENT_PLAN_INVALID"  # 422
ERR_REFUND_NOT_ALLOWED = "ERR_REFUND_NOT_ALLOWED"      # 422


def unauthenticated(msg="Missing or unrecognized X-User-Role, or missing X-User-ID for an entity-backed role"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Role not permitted for this endpoint, or caller does not own the target resource"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_state(msg="The resource's current state does not permit this operation"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def invalid_request(msg="Missing required field, invalid enum member, or numeric range violation"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)
