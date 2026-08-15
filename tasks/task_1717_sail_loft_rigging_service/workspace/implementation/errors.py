"""Error classes and error ID constants from the scaffold error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERR_MISSING_OR_INVALID_USER_CONTEXT = "ERR_MISSING_OR_INVALID_USER_CONTEXT"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_CREDIT_LIMIT_EXCEEDED = "ERR_CREDIT_LIMIT_EXCEEDED"
ERR_RESOURCE_NOT_FOUND = "ERR_RESOURCE_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_DESIGN_NOT_IN_REQUIRED_STATE = "ERR_DESIGN_NOT_IN_REQUIRED_STATE"
ERR_UNRESOLVED_RIGGING_FAIL = "ERR_UNRESOLVED_RIGGING_FAIL"
ERR_MAST_SLOT_OVERLAP = "ERR_MAST_SLOT_OVERLAP"
ERR_BAY_WINDOW_CONFLICT = "ERR_BAY_WINDOW_CONFLICT"
ERR_MEASUREMENT_NOT_FROZEN = "ERR_MEASUREMENT_NOT_FROZEN"
ERR_CLOTH_SHORTAGE = "ERR_CLOTH_SHORTAGE"
ERR_FAIL_NOT_SUPERSEDED = "ERR_FAIL_NOT_SUPERSEDED"
ERR_STALE_BOAT_VERSION = "ERR_STALE_BOAT_VERSION"
ERR_CLASS_MISMATCH = "ERR_CLASS_MISMATCH"
ERR_INVALID_MEASUREMENT = "ERR_INVALID_MEASUREMENT"
ERR_WARRANTY_WINDOW_EXPIRED = "ERR_WARRANTY_WINDOW_EXPIRED"
ERR_ACCOUNT_RULE_VIOLATION = "ERR_ACCOUNT_RULE_VIOLATION"


def missing_context(msg="X-User-ID or X-User-Role header missing or malformed"):
    return ApiError(ERR_MISSING_OR_INVALID_USER_CONTEXT, msg, 400)


def forbidden_role(msg="Role not permitted for this endpoint"):
    return ApiError(ERR_FORBIDDEN_ROLE, msg, 403)


def not_found(msg="A path resource id does not exist"):
    return ApiError(ERR_RESOURCE_NOT_FOUND, msg, 404)


def invalid_state(msg="Target resource is not in a valid source state for the requested transition"):
    return ApiError(ERR_INVALID_STATE, msg, 409)


def design_not_in_required_state(msg="SailDesign must be SUBMITTED for approve, or APPROVED for lock-design"):
    return ApiError(ERR_DESIGN_NOT_IN_REQUIRED_STATE, msg, 409)


def unresolved_rigging_fail(msg="A REPORTED RiggingInspection with verdict FAIL exists for the boat, or boat is OUT_OF_SERVICE"):
    return ApiError(ERR_UNRESOLVED_RIGGING_FAIL, msg, 409)


def mast_slot_overlap(msg="Requested mast service slot overlaps an existing non-terminal MastServiceEvent on the same boat"):
    return ApiError(ERR_MAST_SLOT_OVERLAP, msg, 409)


def bay_window_conflict(msg="Requested bay window violates the closed-interval + 1-day-turnaround rule"):
    return ApiError(ERR_BAY_WINDOW_CONFLICT, msg, 409)


def measurement_not_frozen(msg="Referenced MeasurementSheet is missing or not in FROZEN status at design submission"):
    return ApiError(ERR_MEASUREMENT_NOT_FROZEN, msg, 409)


def cloth_shortage(msg="reserved_cloth_sqm exceeds ClothLedgerEntry.available_sqm for the design's cloth_tier"):
    return ApiError(ERR_CLOTH_SHORTAGE, msg, 409)


def fail_not_superseded(msg="Closing a FAIL-verdict inspection requires a passing REPORTED replacement inspection for the same boat and scope"):
    return ApiError(ERR_FAIL_NOT_SUPERSEDED, msg, 409)


def stale_boat_version(msg="expected_boat_version does not match the boat's current version"):
    return ApiError(ERR_STALE_BOAT_VERSION, msg, 412)


def class_mismatch(msg="Certificate racing_class differs from boat.racing_class, boat.racing_class is NONE, or referenced sheet is not FROZEN"):
    return ApiError(ERR_CLASS_MISMATCH, msg, 422)


def invalid_measurement(msg="One or more of i_height_m, j_base_m, p_main_m, e_main_m is not a positive number at freeze time"):
    return ApiError(ERR_INVALID_MEASUREMENT, msg, 422)


def warranty_window_expired(msg="Warranty claim filed more than 730 days after delivery"):
    return ApiError(ERR_WARRANTY_WINDOW_EXPIRED, msg, 422)


def account_rule_violation(msg="Suspend/reinstate/close preconditions on outstanding balance or active boats are violated"):
    return ApiError(ERR_ACCOUNT_RULE_VIOLATION, msg, 422)


def credit_limit_exceeded(msg="Customer outstanding balance plus the projected quote exceeds the credit limit"):
    return ApiError(ERR_CREDIT_LIMIT_EXCEEDED, msg, 402)


def invalid_request(msg="Missing required field, type mismatch, or enum value outside the declared set"):
    return ApiError(ERR_INVALID_REQUEST, msg, 400)
