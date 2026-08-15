"""Error catalog: exact error_id strings and HTTP statuses from PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- Auth ---
ERR_MISSING_OR_INVALID_USER_CONTEXT = "ERR_MISSING_OR_INVALID_USER_CONTEXT"  # 400
ERR_FORBIDDEN = "ERR_FORBIDDEN"                                              # 403
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"                            # 403

# --- Existence ---
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                              # 404
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"                          # 422

# --- State ---
ERR_INVALID_STATE = "ERR_INVALID_STATE"                                      # 409

# --- Fiscal / Pool ---
ERR_INSUFFICIENT_POOL = "ERR_INSUFFICIENT_POOL"                              # 409
ERR_QUARTER_MISMATCH = "ERR_QUARTER_MISMATCH"                                # 409
ERR_FUTURE_QUARTER = "ERR_FUTURE_QUARTER"                                    # 409
ERR_SPLIT_MISMATCH = "ERR_SPLIT_MISMATCH"                                    # 500

# --- Business constraint (program/supplier) ---
ERR_INVALID_TIER_SCHEDULE = "ERR_INVALID_TIER_SCHEDULE"                      # 422
ERR_INVALID_EXCLUSIVITY = "ERR_INVALID_EXCLUSIVITY"                          # 422
ERR_DUPLICATE_PROGRAM_CODE = "ERR_DUPLICATE_PROGRAM_CODE"                    # 409
ERR_SUPPLIER_NOT_ONBOARDED = "ERR_SUPPLIER_NOT_ONBOARDED"                    # 409
ERR_SUPPLIER_HAS_ACTIVE_PROGRAMS = "ERR_SUPPLIER_HAS_ACTIVE_PROGRAMS"        # 409
ERR_PROGRAM_NOT_OPEN = "ERR_PROGRAM_NOT_OPEN"                                # 409
ERR_PROGRAM_HAS_ENROLLMENTS = "ERR_PROGRAM_HAS_ENROLLMENTS"                  # 409
ERR_MEMBER_NOT_ACTIVE = "ERR_MEMBER_NOT_ACTIVE"                              # 409
ERR_OPEN_CLAWBACK = "ERR_OPEN_CLAWBACK"                                      # 409

# --- Concurrency ---
ERR_STALE_PROGRAM_VERSION = "ERR_STALE_PROGRAM_VERSION"                      # 412
ERR_STALE_DISTRIBUTION_VERSION = "ERR_STALE_DISTRIBUTION_VERSION"            # 412

# --- Request shape ---
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                                  # 400


def err_missing_context(msg="X-User-ID or X-User-Role header missing or malformed"):
    return ApiError(ERR_MISSING_OR_INVALID_USER_CONTEXT, 400, msg)


def err_forbidden(msg="Role not permitted for this endpoint"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def err_not_owner(msg="Caller does not own the target resource"):
    return ApiError(ERR_NOT_RESOURCE_OWNER, 403, msg)


def err_not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def err_reference(msg="Body foreign key references a non-existent entity"):
    return ApiError(ERR_REFERENCE_NOT_FOUND, 422, msg)


def err_state(msg="Target resource is not in a state that permits this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def err_invalid_request(msg="Request body failed schema validation"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)
