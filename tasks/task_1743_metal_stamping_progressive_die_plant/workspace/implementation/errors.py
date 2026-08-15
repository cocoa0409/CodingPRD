"""Error classes and error ID constants per the PRD error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_QUALITY_HOLD = "ERR_QUALITY_HOLD"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_PRESS_CAPACITY_INSUFFICIENT = "ERR_PRESS_CAPACITY_INSUFFICIENT"
ERR_MATERIAL_MISMATCH = "ERR_MATERIAL_MISMATCH"
ERR_PRESS_SCHEDULE_CONFLICT = "ERR_PRESS_SCHEDULE_CONFLICT"
ERR_CHANGEOVER_CONFLICT = "ERR_CHANGEOVER_CONFLICT"
ERR_PPAP_LEVEL_MISMATCH = "ERR_PPAP_LEVEL_MISMATCH"
ERR_RELEASE_GATE_UNMET = "ERR_RELEASE_GATE_UNMET"
ERR_COIL_WEIGHT_EXCEEDED = "ERR_COIL_WEIGHT_EXCEEDED"
ERR_PRICE_FLOOR_BREACH = "ERR_PRICE_FLOOR_BREACH"
ERR_DUPLICATE = "ERR_DUPLICATE"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_NO_SHOTS_RECORDED = "ERR_NO_SHOTS_RECORDED"
ERR_REJECT_COUNT_EXCEEDS_SHOTS = "ERR_REJECT_COUNT_EXCEEDS_SHOTS"
ERR_RETURN_QUANTITY_EXCEEDED = "ERR_RETURN_QUANTITY_EXCEEDED"
ERR_ORDER_NOT_COMPLETED = "ERR_ORDER_NOT_COMPLETED"
ERR_AUDIT_FINDINGS_REQUIRED = "ERR_AUDIT_FINDINGS_REQUIRED"


def unauthenticated(msg="Missing or invalid X-User-Role / X-User-ID headers"):
    return ApiError(ERR_UNAUTHENTICATED, msg, 401)


def unauthorized(msg="Role not permitted for this endpoint"):
    return ApiError(ERR_UNAUTHORIZED, msg, 403)


def not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def invalid_state(msg="State-machine precondition violated for the requested transition"):
    return ApiError(ERR_INVALID_STATE, msg, 409)


def stale_version(msg="OCC expected version does not match the current entity version"):
    return ApiError(ERR_STALE_VERSION, msg, 412)


def quality_hold(msg="Quality hold blocks this operation"):
    return ApiError(ERR_QUALITY_HOLD, msg, 422)


def segregation(msg="Acting user created the record they are trying to disposition"):
    return ApiError(ERR_SEGREGATION_OF_DUTIES, msg, 422)


def capacity(msg="Press tonnage or bed width below die requirement"):
    return ApiError(ERR_PRESS_CAPACITY_INSUFFICIENT, msg, 422)


def material_mismatch(msg="Coil material spec or thickness does not match the part"):
    return ApiError(ERR_MATERIAL_MISMATCH, msg, 422)


def schedule_conflict(msg="Run window overlaps another SCHEDULED/RUNNING run on the same press"):
    return ApiError(ERR_PRESS_SCHEDULE_CONFLICT, msg, 409)


def changeover_conflict(msg="Changeover window plus 30-minute teardown buffer overlaps another changeover or run on the same press"):
    return ApiError(ERR_CHANGEOVER_CONFLICT, msg, 409)


def ppap_level_mismatch(msg="Submission level differs from part.ppap_required_level, or control plan missing for level >= 2"):
    return ApiError(ERR_PPAP_LEVEL_MISMATCH, msg, 422)


def release_gate(msg="Order release gate failed"):
    return ApiError(ERR_RELEASE_GATE_UNMET, msg, 422)


def coil_weight(msg="Planned or actual consumption exceeds coil.remaining_weight_kg"):
    return ApiError(ERR_COIL_WEIGHT_EXCEEDED, msg, 422)


def price_floor(msg="Index-adjusted piece price would fall below 1 cent at order close"):
    return ApiError(ERR_PRICE_FLOOR_BREACH, msg, 422)


def duplicate(msg="Unique constraint violated"):
    return ApiError(ERR_DUPLICATE, msg, 409)


def invalid_request(msg="Malformed request"):
    return ApiError(ERR_INVALID_REQUEST, msg, 400)


def no_shots(msg="Run completion with shots_recorded == 0"):
    return ApiError(ERR_NO_SHOTS_RECORDED, msg, 422)


def rejects_exceed(msg="Recorded rejects exceed shots_recorded at completion"):
    return ApiError(ERR_REJECT_COUNT_EXCEEDS_SHOTS, msg, 422)


def return_exceeded(msg="Cumulative outside-processing returns would exceed quantity_sent"):
    return ApiError(ERR_RETURN_QUANTITY_EXCEEDED, msg, 422)


def order_not_completed(msg="close-short attempted while parent order is not COMPLETED"):
    return ApiError(ERR_ORDER_NOT_COMPLETED, msg, 409)


def audit_findings(msg="Recording audit result FAIL with findings_count < 1"):
    return ApiError(ERR_AUDIT_FINDINGS_REQUIRED, msg, 422)
