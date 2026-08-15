"""Error classes and error ID constants (PRD §5 error catalogue).

Alias error names in the PRD/scaffold prose (ERR_DUPLICATE_LICENSE_NO,
ERR_DUPLICATE_DEVICE_SERIAL, ERR_DUPLICATE_PLAN_YEAR,
ERR_OPEN_EVENTS_BLOCK_DEACTIVATION, ERR_TECHNICIAN_HAS_OPEN_EVENTS,
ERR_SYSTEMS_STILL_IN_SERVICE, ERR_UNRESOLVED_FALSE_ALARMS,
ERR_OPEN_IMPAIRMENT_EXISTS, ERR_OPEN_PERMIT_EXISTS,
ERR_DEVICE_HAS_OPEN_DEFICIENCY, ERR_SYSTEM_CATEGORY_MISMATCH,
ERR_DEVICE_REPLACEMENT_MISMATCH) are carried on the wire by their canonical
class id: ERR_DUPLICATE_CONSTRAINT / ERR_OPEN_ITEMS_BLOCK /
ERR_CROSS_REFERENCE_MISMATCH respectively.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_ENUM = "ERR_INVALID_ENUM"
ERR_INVALID_DATE_RANGE = "ERR_INVALID_DATE_RANGE"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_CONTRACTOR_POSTURE_BLOCKED = "ERR_CONTRACTOR_POSTURE_BLOCKED"
ERR_SYSTEM_OUT_OF_SERVICE = "ERR_SYSTEM_OUT_OF_SERVICE"
ERR_SYSTEM_IMPAIRED = "ERR_SYSTEM_IMPAIRED"
ERR_LICENSE_NOT_VALID = "ERR_LICENSE_NOT_VALID"
ERR_TECHNICIAN_NOT_ASSIGNED = "ERR_TECHNICIAN_NOT_ASSIGNED"
ERR_TECHNICIAN_CAPACITY = "ERR_TECHNICIAN_CAPACITY"
ERR_IMPAIRMENT_OVERLAP = "ERR_IMPAIRMENT_OVERLAP"
ERR_DUPLICATE_CONSTRAINT = "ERR_DUPLICATE_CONSTRAINT"
ERR_CROSS_REFERENCE_MISMATCH = "ERR_CROSS_REFERENCE_MISMATCH"
ERR_OPEN_ITEMS_BLOCK = "ERR_OPEN_ITEMS_BLOCK"
ERR_CRITICAL_NOT_WAIVABLE = "ERR_CRITICAL_NOT_WAIVABLE"
ERR_EMPTY_PLAN = "ERR_EMPTY_PLAN"
ERR_EVENT_NOT_COMPLETED = "ERR_EVENT_NOT_COMPLETED"
ERR_EVENT_NOT_YET_DUE = "ERR_EVENT_NOT_YET_DUE"
ERR_UNRESOLVED_OVERDUE_DEFICIENCIES = "ERR_UNRESOLVED_OVERDUE_DEFICIENCIES"
ERR_REPORT_REVISION_INVALID = "ERR_REPORT_REVISION_INVALID"
ERR_PUMP_COORDINATION_REQUIRED = "ERR_PUMP_COORDINATION_REQUIRED"
ERR_PERMIT_EXPIRED = "ERR_PERMIT_EXPIRED"
ERR_POST_MOD_INSPECTION_REQUIRED = "ERR_POST_MOD_INSPECTION_REQUIRED"
ERR_DEFICIENCY_NOT_EXTENSIBLE = "ERR_DEFICIENCY_NOT_EXTENSIBLE"


def unauthenticated(msg="Missing or unrecognized authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="Role not authorized for this endpoint"):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def segregation_of_duties(msg="Verifying actor must differ from the attesting actor"):
    return ApiError(ERR_SEGREGATION_OF_DUTIES, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def reference_not_found(msg="Referenced resource not found"):
    return ApiError(ERR_REFERENCE_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid request"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def invalid_enum(msg="Enum value outside its declared set"):
    return ApiError(ERR_INVALID_ENUM, 422, msg)


def invalid_date_range(msg="End must be strictly after start"):
    return ApiError(ERR_INVALID_DATE_RANGE, 422, msg)


def invalid_state(msg="Invalid state for this operation"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_version(msg="Expected version does not match the parent's current version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def posture_blocked(msg="Contractor posture or status blocks this write"):
    return ApiError(ERR_CONTRACTOR_POSTURE_BLOCKED, 409, msg)


def system_out_of_service(msg="System is out of service"):
    return ApiError(ERR_SYSTEM_OUT_OF_SERVICE, 409, msg)


def system_impaired(msg="System impairment status is not NORMAL"):
    return ApiError(ERR_SYSTEM_IMPAIRED, 422, msg)


def license_not_valid(msg="Technician lacks an ACTIVE license of the required class valid for the relevant date"):
    return ApiError(ERR_LICENSE_NOT_VALID, 422, msg)


def technician_not_assigned(msg="Acting technician is not the event's lead technician"):
    return ApiError(ERR_TECHNICIAN_NOT_ASSIGNED, 403, msg)


def technician_capacity(msg="Lead technician would exceed 3 overlapping engagements"):
    return ApiError(ERR_TECHNICIAN_CAPACITY, 409, msg)


def impairment_overlap(msg="Impairment overlaps another or starts inside the 4-hour re-certification buffer"):
    return ApiError(ERR_IMPAIRMENT_OVERLAP, 409, msg)


def duplicate_constraint(msg="Uniqueness constraint violated"):
    return ApiError(ERR_DUPLICATE_CONSTRAINT, 409, msg)


def cross_reference_mismatch(msg="Cross-aggregate reference mismatch"):
    return ApiError(ERR_CROSS_REFERENCE_MISMATCH, 422, msg)


def open_items_block(msg="Open items block this operation"):
    return ApiError(ERR_OPEN_ITEMS_BLOCK, 409, msg)


def critical_not_waivable(msg="A CRITICAL deficiency is never waivable"):
    return ApiError(ERR_CRITICAL_NOT_WAIVABLE, 422, msg)


def empty_plan(msg="Plan requires at least one inspection event"):
    return ApiError(ERR_EMPTY_PLAN, 422, msg)


def event_not_completed(msg="Parent event is not COMPLETED"):
    return ApiError(ERR_EVENT_NOT_COMPLETED, 409, msg)


def event_not_yet_due(msg="Event has not reached its scheduled start"):
    return ApiError(ERR_EVENT_NOT_YET_DUE, 422, msg)


def unresolved_overdue_deficiencies(msg="Event has deficiencies past their correction deadline and not VERIFIED/WAIVED"):
    return ApiError(ERR_UNRESOLVED_OVERDUE_DEFICIENCIES, 409, msg)


def report_revision_invalid(msg="revision_of_id must reference a REJECTED report on the same event"):
    return ApiError(ERR_REPORT_REVISION_INVALID, 422, msg)


def pump_coordination_required(msg="ANNUAL_FLOW pump test requires a COMPLETED coordinated event on the same system"):
    return ApiError(ERR_PUMP_COORDINATION_REQUIRED, 422, msg)


def permit_expired(msg="Permit validity window has elapsed"):
    return ApiError(ERR_PERMIT_EXPIRED, 409, msg)


def post_mod_inspection_required(msg="A passing post-modification inspection must be COMPLETED after work commenced"):
    return ApiError(ERR_POST_MOD_INSPECTION_REQUIRED, 409, msg)


def deficiency_not_extensible(msg="Only an OPEN NONCRITICAL deficiency never before extended may be extended"):
    return ApiError(ERR_DEFICIENCY_NOT_EXTENSIBLE, 422, msg)
