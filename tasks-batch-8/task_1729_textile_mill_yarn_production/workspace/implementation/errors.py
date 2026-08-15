"""Error catalog — every error_id and HTTP status from SCAFFOLD.yaml §1.6 / PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(message="X-User-Role header missing or unrecognized"):
    return ApiError("ERR_UNAUTHENTICATED", 401, message)


def err_forbidden(message="Role not permitted to invoke this endpoint"):
    return ApiError("ERR_FORBIDDEN", 403, message)


def err_not_found(message="Path template id does not resolve to an existing entity"):
    return ApiError("ERR_NOT_FOUND", 404, message)


def err_reference_not_found(message="FK payload field references a non-existent entity"):
    return ApiError("ERR_REFERENCE_NOT_FOUND", 422, message)


def err_invalid_state(message="Target entity's current state does not permit the requested transition"):
    return ApiError("ERR_INVALID_STATE", 409, message)


def err_stale_version(message="OCC expected version does not match the parent's current version"):
    return ApiError("ERR_STALE_VERSION", 412, message)


def err_quality_gate(message="Quality-gate violation"):
    return ApiError("ERR_QUALITY_GATE_FAILED", 422, message)


def err_duplicate_key(message="Uniqueness violation on recipe_code or machine_code"):
    return ApiError("ERR_DUPLICATE_KEY", 409, message)


def err_window_conflict(message="Temporal overlap on machine window or vat buffer conflict"):
    return ApiError("ERR_WINDOW_CONFLICT", 409, message)


def err_referential_violation(message="Referential integrity violation"):
    return ApiError("ERR_REFERENTIAL_VIOLATION", 422, message)


def err_insufficient_capacity(message="Yarn lot lacks greige yards or fiber lot lacks available weight"):
    return ApiError("ERR_INSUFFICIENT_CAPACITY", 422, message)


def err_count_out_of_range(message="Recipe's target_yarn_count_ne outside machine's supported range"):
    return ApiError("ERR_COUNT_OUT_OF_RANGE", 422, message)


def err_shade_out_of_band(message="LabDip measured_delta_e exceeds ShadeBand tolerance; cannot be approved"):
    return ApiError("ERR_SHADE_OUT_OF_BAND", 422, message)


def err_invalid_request(message="Malformed payload, missing required field, or field type/range violation"):
    return ApiError("ERR_INVALID_REQUEST", 400, message)


def err_second_quality_not_allocatable(message="Roll flagged is_second_quality cannot be allocated to a normal customer order"):
    return ApiError("ERR_SECOND_QUALITY_NOT_ALLOCATABLE", 422, message)
