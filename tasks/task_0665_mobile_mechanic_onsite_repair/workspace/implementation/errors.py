"""Error classes and error ID constants (from SCAFFOLD §1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: id -> http status
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_ZONE_MISMATCH = "ERR_ZONE_MISMATCH"
ERR_INSUFFICIENT_SKILL_TIER = "ERR_INSUFFICIENT_SKILL_TIER"
ERR_VISIT_OVERLAP = "ERR_VISIT_OVERLAP"
ERR_CALLBACK_SLOT_CONFLICT = "ERR_CALLBACK_SLOT_CONFLICT"
ERR_WARRANTY_WINDOW_EXPIRED = "ERR_WARRANTY_WINDOW_EXPIRED"
ERR_FLEET_CREDIT_EXCEEDED = "ERR_FLEET_CREDIT_EXCEEDED"
ERR_FLEET_ACCOUNT_SUSPENDED = "ERR_FLEET_ACCOUNT_SUSPENDED"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_ADDONS_UNRESOLVED = "ERR_ADDONS_UNRESOLVED"
ERR_VALIDATION_PENDING = "ERR_VALIDATION_PENDING"


def unauthenticated(msg="Missing or malformed authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg="Acting role is not permitted for this operation."):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_found(msg="Referenced resource does not exist."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def not_owner(msg="Acting user does not own the targeted resource."):
    return ApiError(ERR_NOT_RESOURCE_OWNER, 403, msg)


def invalid_state(msg="The requested transition is not defined from the resource's current state."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def invalid_request(msg="Request body is structurally invalid."):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def zone_mismatch(msg="Mechanic zone does not match service request zone."):
    return ApiError(ERR_ZONE_MISMATCH, 409, msg)


def insufficient_skill(msg="Mechanic skill tier is insufficient for tow-to-shop."):
    return ApiError(ERR_INSUFFICIENT_SKILL_TIER, 409, msg)


def visit_overlap(msg="Proposed on-site visit overlaps an existing visit for the mechanic."):
    return ApiError(ERR_VISIT_OVERLAP, 409, msg)


def callback_slot_conflict(msg="Callback visit slot conflicts with an existing visit for the mechanic."):
    return ApiError(ERR_CALLBACK_SLOT_CONFLICT, 409, msg)


def warranty_window_expired(msg="Warranty claim filed beyond the warranty window."):
    return ApiError(ERR_WARRANTY_WINDOW_EXPIRED, 409, msg)


def fleet_credit_exceeded(msg="Projected fleet outstanding balance would exceed the credit limit."):
    return ApiError(ERR_FLEET_CREDIT_EXCEEDED, 402, msg)


def fleet_account_suspended(msg="Fleet account is suspended."):
    return ApiError(ERR_FLEET_ACCOUNT_SUSPENDED, 409, msg)


def stale_version(msg="expected version does not match the current resource version."):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def addons_unresolved(msg="One or more inspection findings remain proposed."):
    return ApiError(ERR_ADDONS_UNRESOLVED, 409, msg)


def validation_pending(msg="Decisions list does not exactly cover the proposed findings."):
    return ApiError(ERR_VALIDATION_PENDING, 422, msg)
