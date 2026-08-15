"""Error classes and error ID constants (per scaffold §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_INSPECTION_EXISTS = "ERR_INSPECTION_EXISTS"
ERR_PERMIT_SUSPENDED = "ERR_PERMIT_SUSPENDED"
ERR_ACCEPTANCE_REQUIRED = "ERR_ACCEPTANCE_REQUIRED"
ERR_SOD_VIOLATION = "ERR_SOD_VIOLATION"
ERR_PAD_INCOMPATIBLE = "ERR_PAD_INCOMPATIBLE"
ERR_PAD_NOT_AVAILABLE = "ERR_PAD_NOT_AVAILABLE"
ERR_PAD_WINDOW_OVERLAP = "ERR_PAD_WINDOW_OVERLAP"
ERR_FLUID_CONSTRAINED = "ERR_FLUID_CONSTRAINED"
ERR_CREDIT_LIMIT_EXCEEDED = "ERR_CREDIT_LIMIT_EXCEEDED"
ERR_INSUFFICIENT_FLUID = "ERR_INSUFFICIENT_FLUID"
ERR_TANK_CAPACITY_EXCEEDED = "ERR_TANK_CAPACITY_EXCEEDED"
ERR_PERMIT_VOLUME_EXCEEDED = "ERR_PERMIT_VOLUME_EXCEEDED"
ERR_SPILL_DEADLINE_PASSED = "ERR_SPILL_DEADLINE_PASSED"
ERR_RECYCLE_QUALITY = "ERR_RECYCLE_QUALITY"
ERR_INSUFFICIENT_COLLECTED_GLYCOL = "ERR_INSUFFICIENT_COLLECTED_GLYCOL"
ERR_OPERATION_INVOICED = "ERR_OPERATION_INVOICED"


def unauthenticated(msg="Missing or unknown X-User-Role / X-User-ID headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Role not permitted on endpoint"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Referenced resource id does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Missing required field, bad enum value, malformed datetime, or non-positive quantities"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def stale_version(msg="expected_*_version does not match the parent entity's current version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def invalid_state(msg="Resource not in a valid from-state for the requested transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def inspection_exists(msg="An inspection of the same kind already exists for the operation"):
    return ApiError(ERR_INSPECTION_EXISTS, 409, msg)


def permit_suspended(msg="Station posture is PERMIT_SUSPENDED; assign blocked"):
    return ApiError(ERR_PERMIT_SUSPENDED, 409, msg)


def acceptance_required(msg="Spray start without an ACCEPTANCE PASS inspection on the operation"):
    return ApiError(ERR_ACCEPTANCE_REQUIRED, 409, msg)


def sod_violation(msg="Segregation of duties breached"):
    return ApiError(ERR_SOD_VIOLATION, 409, msg)


def pad_incompatible(msg="Pad max_size_class smaller than request size_class"):
    return ApiError(ERR_PAD_INCOMPATIBLE, 409, msg)


def pad_not_available(msg="Pad not in AVAILABLE status"):
    return ApiError(ERR_PAD_NOT_AVAILABLE, 409, msg)


def pad_window_overlap(msg="Planned window overlaps a non-terminal operation window on the pad"):
    return ApiError(ERR_PAD_WINDOW_OVERLAP, 409, msg)


def fluid_constrained(msg="Station posture FLUID_CONSTRAINED, or request is UNRESERVED, at assign time"):
    return ApiError(ERR_FLUID_CONSTRAINED, 409, msg)


def credit_limit_exceeded(msg="Airline outstanding balance plus the new request's estimated charge would exceed credit_limit_cents"):
    return ApiError(ERR_CREDIT_LIMIT_EXCEEDED, 402, msg)


def insufficient_fluid(msg="actual_liters exceeds tank.on_hand_liters at complete"):
    return ApiError(ERR_INSUFFICIENT_FLUID, 409, msg)


def tank_capacity_exceeded(msg="Replenish would push on_hand_liters above capacity_liters"):
    return ApiError(ERR_TANK_CAPACITY_EXCEEDED, 409, msg)


def permit_volume_exceeded(msg="Rolling-window discharge volume would exceed rolling_window_max_liters"):
    return ApiError(ERR_PERMIT_VOLUME_EXCEEDED, 409, msg)


def spill_deadline_passed(msg="Confirm attempted after occurred_at + 120 minutes"):
    return ApiError(ERR_SPILL_DEADLINE_PASSED, 409, msg)


def recycle_quality(msg="Shipment concentration below contract min_concentration_pct"):
    return ApiError(ERR_RECYCLE_QUALITY, 409, msg)


def insufficient_collected_glycol(msg="Shipment volume exceeds station collected_pool_liters"):
    return ApiError(ERR_INSUFFICIENT_COLLECTED_GLYCOL, 409, msg)


def operation_invoiced(msg="Void blocked: a DRAFT or ISSUED invoice exists for the operation"):
    return ApiError(ERR_OPERATION_INVOICED, 409, msg)
