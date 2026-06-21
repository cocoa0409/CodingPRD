"""Error classes and error ID constants (PRD §5 catalogue)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalogue (PRD §5 / SCAFFOLD 1.6)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"               # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"                 # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                           # 404
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"         # 403
ERR_AGENT_WRONG_DEPARTMENT = "ERR_AGENT_WRONG_DEPARTMENT" # 403
ERR_INVALID_STATE = "ERR_INVALID_STATE"                   # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                   # 412
ERR_CATEGORY_INACTIVE = "ERR_CATEGORY_INACTIVE"           # 409
ERR_GEOLOCATION_REQUIRED = "ERR_GEOLOCATION_REQUIRED"     # 422
ERR_CLUSTER_CATEGORY_MISMATCH = "ERR_CLUSTER_CATEGORY_MISMATCH"  # 409
ERR_OUTSIDE_CLUSTER_RADIUS = "ERR_OUTSIDE_CLUSTER_RADIUS" # 409
ERR_NO_SLA_POLICY = "ERR_NO_SLA_POLICY"                   # 409
ERR_REOPEN_WINDOW_CLOSED = "ERR_REOPEN_WINDOW_CLOSED"     # 409
ERR_CANONICAL_NOT_RESOLVED = "ERR_CANONICAL_NOT_RESOLVED" # 409
ERR_OPEN_ESCALATION_BLOCKS_CLOSE = "ERR_OPEN_ESCALATION_BLOCKS_CLOSE"  # 409
ERR_TIER2_REQUIRES_SUPERVISOR = "ERR_TIER2_REQUIRES_SUPERVISOR"  # 403
ERR_INVALID_SCORE = "ERR_INVALID_SCORE"                   # 422
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"               # 422
ERR_DUPLICATE_WORK_ORDER = "ERR_DUPLICATE_WORK_ORDER"     # 409
ERR_WINDOW_SCOPE_INVALID = "ERR_WINDOW_SCOPE_INVALID"     # 422
ERR_WINDOW_OVERLAP = "ERR_WINDOW_OVERLAP"                 # 409
ERR_WINDOW_BLOCKS_ROUTING = "ERR_WINDOW_BLOCKS_ROUTING"   # 409


def unauthenticated(msg="Missing or unknown authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg="Role is not permitted to invoke this operation."):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_found(msg="Referenced resource does not exist."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def not_resource_owner(msg="Acting citizen does not own the target resource."):
    return ApiError(ERR_NOT_RESOURCE_OWNER, 403, msg)


def agent_wrong_department(msg="Acting agent does not belong to the work order's department."):
    return ApiError(ERR_AGENT_WRONG_DEPARTMENT, 403, msg)


def invalid_state(msg="Target resource is not in a state from which this transition is defined."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_version(msg="Optimistic-concurrency version mismatch."):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def category_inactive(msg="Referenced category is inactive."):
    return ApiError(ERR_CATEGORY_INACTIVE, 409, msg)


def geolocation_required(msg="Category requires geolocation but lat/lng not both present."):
    return ApiError(ERR_GEOLOCATION_REQUIRED, 422, msg)


def cluster_category_mismatch(msg="Member request category differs from the cluster category."):
    return ApiError(ERR_CLUSTER_CATEGORY_MISMATCH, 409, msg)


def outside_cluster_radius(msg="Member request lies outside the cluster radius."):
    return ApiError(ERR_OUTSIDE_CLUSTER_RADIUS, 409, msg)


def no_sla_policy(msg="No SLA policy exists for this category and priority."):
    return ApiError(ERR_NO_SLA_POLICY, 409, msg)


def reopen_window_closed(msg="Reopen window has closed."):
    return ApiError(ERR_REOPEN_WINDOW_CLOSED, 409, msg)


def canonical_not_resolved(msg="Canonical request is not RESOLVED or CLOSED."):
    return ApiError(ERR_CANONICAL_NOT_RESOLVED, 409, msg)


def open_escalation_blocks_close(msg="Request has an open escalation and cannot be closed."):
    return ApiError(ERR_OPEN_ESCALATION_BLOCKS_CLOSE, 409, msg)


def tier2_requires_supervisor(msg="Resolving a TIER2 escalation requires a supervisor agent or Dispatcher/SystemAdmin."):
    return ApiError(ERR_TIER2_REQUIRES_SUPERVISOR, 403, msg)


def invalid_score(msg="Survey score must be an integer in [1,5]."):
    return ApiError(ERR_INVALID_SCORE, 422, msg)


def invalid_request(msg="Request body fails schema validation."):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def duplicate_work_order(msg="Request already has a work order."):
    return ApiError(ERR_DUPLICATE_WORK_ORDER, 409, msg)


def window_scope_invalid(msg="ServiceWindow scope is invalid for its window_type."):
    return ApiError(ERR_WINDOW_SCOPE_INVALID, 422, msg)


def window_overlap(msg="ServiceWindow overlaps an existing same-type, same-scope window."):
    return ApiError(ERR_WINDOW_OVERLAP, 409, msg)


def window_blocks_routing(msg="Routing blocked by an active maintenance or blackout window."):
    return ApiError(ERR_WINDOW_BLOCKS_ROUTING, 409, msg)
