"""Error classes and error-id catalog (PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http status (PRD §5 / scaffold §1.6)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_PAGINATION = "ERR_INVALID_PAGINATION"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_PROJECT_VERSION = "ERR_STALE_PROJECT_VERSION"
ERR_ENGINEERING_UNDERRATED = "ERR_ENGINEERING_UNDERRATED"
ERR_ENGINEERING_PENDING = "ERR_ENGINEERING_PENDING"
ERR_HOA_NOT_APPROVED = "ERR_HOA_NOT_APPROVED"
ERR_WEATHER_UNSAFE = "ERR_WEATHER_UNSAFE"
ERR_CREW_NOT_CERTIFIED = "ERR_CREW_NOT_CERTIFIED"
ERR_CREW_INACTIVE = "ERR_CREW_INACTIVE"
ERR_CREW_DOUBLE_BOOKED = "ERR_CREW_DOUBLE_BOOKED"
ERR_SITE_WINDOW_CONFLICT = "ERR_SITE_WINDOW_CONFLICT"
ERR_INVALID_WINDOW = "ERR_INVALID_WINDOW"
ERR_PERMIT_EXPIRED = "ERR_PERMIT_EXPIRED"
ERR_RESUBMIT_LIMIT = "ERR_RESUBMIT_LIMIT"
ERR_PRINCIPAL_EXCEEDED = "ERR_PRINCIPAL_EXCEEDED"
ERR_DOWNPAYMENT_EXCEEDS_TOTAL = "ERR_DOWNPAYMENT_EXCEEDS_TOTAL"
ERR_PUNCHLIST_REQUIRED = "ERR_PUNCHLIST_REQUIRED"


# Convenience constructors with the pinned HTTP statuses from PRD §5.
def unauthenticated(msg="Missing or unknown user context."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg="Role not permitted for this operation."):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_resource_owner(msg="Acting on a resource you do not own."):
    return ApiError(ERR_NOT_RESOURCE_OWNER, 403, msg)


def not_found(msg="Entity not found."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid request body."):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def invalid_pagination(msg="Invalid pagination parameters."):
    return ApiError(ERR_INVALID_PAGINATION, 400, msg)


def invalid_state(msg="Entity not in a valid state for this transition."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_project_version(msg="Project version is stale."):
    return ApiError(ERR_STALE_PROJECT_VERSION, 412, msg)
