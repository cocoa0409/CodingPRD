"""Error catalog for the Regulatory Change Management API.

Every error id and HTTP status below is taken from the SCAFFOLD.yaml error
table (PRD §5). Do not invent new ids for spec'd failure modes.
"""


class ApiError(Exception):
    """Exception carrying the exact error_id, HTTP status, and message."""

    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- 400 ---
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"

# --- 403 ---
ERR_UNAUTHORIZED_ROLE = "ERR_UNAUTHORIZED_ROLE"
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"
ERR_SEGREGATION_OF_DUTIES_VIOLATION = "ERR_SEGREGATION_OF_DUTIES_VIOLATION"
ERR_OWNER_SUSPENDED = "ERR_OWNER_SUSPENDED"

# --- 404 ---
ERR_NOT_FOUND = "ERR_NOT_FOUND"

# --- 409 (state family) ---
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_PLAN_NOT_SUBMITTED = "ERR_PLAN_NOT_SUBMITTED"
ERR_PLAN_NOT_COMPLETED = "ERR_PLAN_NOT_COMPLETED"
ERR_PACKAGE_SEALED = "ERR_PACKAGE_SEALED"
ERR_CHANGE_NOT_SUPERSEDABLE = "ERR_CHANGE_NOT_SUPERSEDABLE"

# --- 409 (constraint family) ---
ERR_DUPLICATE_OBLIGATION_CODE = "ERR_DUPLICATE_OBLIGATION_CODE"
ERR_DUPLICATE_CONTROL_CODE = "ERR_DUPLICATE_CONTROL_CODE"
ERR_DUPLICATE_MAPPING = "ERR_DUPLICATE_MAPPING"
ERR_PLAN_ALREADY_EXISTS = "ERR_PLAN_ALREADY_EXISTS"
ERR_PACKAGE_ALREADY_EXISTS = "ERR_PACKAGE_ALREADY_EXISTS"
ERR_REGISTER_EMPTY = "ERR_REGISTER_EMPTY"
ERR_REPORT_PERIOD_OVERLAP = "ERR_REPORT_PERIOD_OVERLAP"
ERR_ROLLOUT_WINDOW_CONFLICT = "ERR_ROLLOUT_WINDOW_CONFLICT"

# --- 409 (referential family) ---
ERR_CHANGE_NOT_TRIAGED_APPLICABLE = "ERR_CHANGE_NOT_TRIAGED_APPLICABLE"
ERR_OBLIGATION_NOT_ACTIVE = "ERR_OBLIGATION_NOT_ACTIVE"
ERR_OBLIGATION_IN_USE = "ERR_OBLIGATION_IN_USE"
ERR_CONTROL_NOT_ACTIVE = "ERR_CONTROL_NOT_ACTIVE"
ERR_CONTROL_IN_USE = "ERR_CONTROL_IN_USE"
ERR_GAP_NOT_CONFIRMED = "ERR_GAP_NOT_CONFIRMED"

# --- 412 (optimistic concurrency) ---
ERR_STALE_CHANGE_VERSION = "ERR_STALE_CHANGE_VERSION"
ERR_STALE_REGISTER_VERSION = "ERR_STALE_REGISTER_VERSION"
ERR_STALE_CONTROL_VERSION = "ERR_STALE_CONTROL_VERSION"

# --- 422 (temporal family) ---
ERR_DEADLINE_IN_PAST = "ERR_DEADLINE_IN_PAST"
ERR_DEADLINE_EXCEEDS_MANDATE = "ERR_DEADLINE_EXCEEDS_MANDATE"
ERR_INVALID_EXTENSION = "ERR_INVALID_EXTENSION"
ERR_MAX_EXTENSIONS_REACHED = "ERR_MAX_EXTENSIONS_REACHED"
ERR_TRAINING_WINDOW_TOO_SHORT = "ERR_TRAINING_WINDOW_TOO_SHORT"
ERR_RETRACT_WINDOW_CLOSED = "ERR_RETRACT_WINDOW_CLOSED"
ERR_TRAINING_WINDOW_CLOSED = "ERR_TRAINING_WINDOW_CLOSED"
ERR_COMPLETION_THRESHOLD_NOT_MET = "ERR_COMPLETION_THRESHOLD_NOT_MET"
ERR_EXCEPTION_THRESHOLD_NOT_MET = "ERR_EXCEPTION_THRESHOLD_NOT_MET"
ERR_NO_ARTIFACTS = "ERR_NO_ARTIFACTS"
ERR_INVALID_REPORT_PERIOD = "ERR_INVALID_REPORT_PERIOD"

# --- 500 fallback ---
ERR_INTERNAL = "ERR_INTERNAL"


def missing_context():
    return ApiError(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400,
                    "X-User-ID or X-User-Role header missing or role not recognized")


def invalid_request(message):
    return ApiError(ERR_INVALID_REQUEST, 400, message)


def unauthorized_role():
    return ApiError(ERR_UNAUTHORIZED_ROLE, 403,
                    "Caller role is not in the endpoint's role list")


def not_resource_owner():
    return ApiError(ERR_NOT_RESOURCE_OWNER, 403,
                    "BusinessOwner action attempted on a resource whose business_owner_id "
                    "differs from X-User-ID")


def not_found(what="resource"):
    return ApiError(ERR_NOT_FOUND, 404, "%s not found" % what)


def invalid_state(message="State-machine precondition failure for the attempted transition"):
    return ApiError(ERR_INVALID_STATE, 409, message)


def sod_violation():
    return ApiError(ERR_SEGREGATION_OF_DUTIES_VIOLATION, 403,
                    "Same user attempts two segregated steps")
