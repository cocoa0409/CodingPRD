"""Error catalog (PRD §5 / scaffold §1.6). Every error carries error_id, message,
and http_status; the response body uses the exact field names error_id/message."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error ID constants — verbatim from PRD §5 error catalogue.
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"               # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"                 # 403
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"         # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                           # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"               # 422
ERR_INVALID_STATE = "ERR_INVALID_STATE"                   # 409
ERR_PLAN_MISMATCH = "ERR_PLAN_MISMATCH"                   # 409
ERR_NOT_ELIGIBLE = "ERR_NOT_ELIGIBLE"                     # 409
ERR_BILLING_PAST_DUE = "ERR_BILLING_PAST_DUE"             # 409
ERR_MIN_TERM_ELAPSED = "ERR_MIN_TERM_ELAPSED"             # 409
ERR_VEHICLE_SLOT_OVERLAP = "ERR_VEHICLE_SLOT_OVERLAP"     # 409
ERR_COURIER_BUFFER_CONFLICT = "ERR_COURIER_BUFFER_CONFLICT"  # 409
ERR_DUPLICATE_VALUE = "ERR_DUPLICATE_VALUE"               # 409
ERR_ODOMETER_REGRESSION = "ERR_ODOMETER_REGRESSION"       # 422
ERR_STALE_VEHICLE_VERSION = "ERR_STALE_VEHICLE_VERSION"   # 412
ERR_STALE_SUBSCRIPTION_VERSION = "ERR_STALE_SUBSCRIPTION_VERSION"  # 412
ERR_NO_VEHICLE_AVAILABLE = "ERR_NO_VEHICLE_AVAILABLE"     # 409
ERR_INVALID_PAGINATION = "ERR_INVALID_PAGINATION"         # 422


def unauthenticated(msg="Missing or unknown authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg="Acting role is not permitted for this operation."):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_resource_owner(msg="Member does not own this resource."):
    return ApiError(ERR_NOT_RESOURCE_OWNER, 403, msg)


def not_found(msg="A referenced resource does not exist."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Missing required field, wrong type, or enum out of set."):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def invalid_state(msg="Requested transition not defined from current state."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def plan_mismatch(msg="Vehicle plan does not match subscription plan."):
    return ApiError(ERR_PLAN_MISMATCH, 409, msg)


def not_eligible(msg="Applicant is not eligible."):
    return ApiError(ERR_NOT_ELIGIBLE, 409, msg)


def billing_past_due(msg="Operation blocked while billing status is PAST_DUE."):
    return ApiError(ERR_BILLING_PAST_DUE, 409, msg)


def min_term_elapsed(msg="Minimum term has already elapsed."):
    return ApiError(ERR_MIN_TERM_ELAPSED, 409, msg)


def vehicle_slot_overlap(msg="New slot overlaps an existing slot on the same vehicle."):
    return ApiError(ERR_VEHICLE_SLOT_OVERLAP, 409, msg)


def courier_buffer_conflict(msg="New slot violates courier buffer gap."):
    return ApiError(ERR_COURIER_BUFFER_CONFLICT, 409, msg)


def duplicate_value(msg="Uniqueness constraint violated."):
    return ApiError(ERR_DUPLICATE_VALUE, 409, msg)


def odometer_regression(msg="Reported odometer is below the cycle start reading."):
    return ApiError(ERR_ODOMETER_REGRESSION, 422, msg)


def stale_vehicle_version(msg="expected_vehicle_version does not match the live Vehicle.version."):
    return ApiError(ERR_STALE_VEHICLE_VERSION, 412, msg)


def stale_subscription_version(msg="expected_subscription_version does not match the live Subscription.version."):
    return ApiError(ERR_STALE_SUBSCRIPTION_VERSION, 412, msg)


def no_vehicle_available(msg="No AVAILABLE vehicle matching fleet/plan."):
    return ApiError(ERR_NO_VEHICLE_AVAILABLE, 409, msg)


def invalid_pagination(msg="limit/offset outside allowed bounds."):
    return ApiError(ERR_INVALID_PAGINATION, 422, msg)
