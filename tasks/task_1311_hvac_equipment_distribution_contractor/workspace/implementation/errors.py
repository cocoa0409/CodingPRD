"""Error classes and error ID constants (from the scaffold error catalog)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"        # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"              # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                    # 404
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"  # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"        # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"            # 409
ERR_ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"      # 409
ERR_COMPLIANCE_HOLD = "ERR_COMPLIANCE_HOLD"        # 422
ERR_INVALID_CYLINDER_WEIGHT = "ERR_INVALID_CYLINDER_WEIGHT"  # 422
ERR_WINDOW_EXPIRED = "ERR_WINDOW_EXPIRED"          # 422
ERR_WINDOW_OVERLAP = "ERR_WINDOW_OVERLAP"          # 422
ERR_INSTRUCTOR_CONFLICT = "ERR_INSTRUCTOR_CONFLICT"  # 422
ERR_POOL_CAPACITY_EXCEEDED = "ERR_POOL_CAPACITY_EXCEEDED"  # 422
ERR_INVALID_SYSTEM_PAIRING = "ERR_INVALID_SYSTEM_PAIRING"  # 422
ERR_DUPLICATE = "ERR_DUPLICATE"                    # 409
ERR_INVALID_LINE = "ERR_INVALID_LINE"              # 422
ERR_MODEL_NOT_ORDERABLE = "ERR_MODEL_NOT_ORDERABLE"  # 422
ERR_REBATE_MISMATCH = "ERR_REBATE_MISMATCH"        # 422
ERR_WARRANTY_NOT_ACTIVE = "ERR_WARRANTY_NOT_ACTIVE"  # 422
ERR_CREDIT_HOLD = "ERR_CREDIT_HOLD"                # 422
ERR_ACCRUAL_EXCEEDED = "ERR_ACCRUAL_EXCEEDED"      # 422
ERR_STALE_VERSION = "ERR_STALE_VERSION"            # 412
ERR_REVISION_LIMIT = "ERR_REVISION_LIMIT"          # 422
ERR_SEAT_CAPACITY = "ERR_SEAT_CAPACITY"            # 422


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def ref_not_found(msg="Referenced resource not found"):
    return ApiError(ERR_REFERENCE_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid request payload"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def invalid_state(msg="Resource is not in a legal state for this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def already_terminal(msg="Resource is in a terminal state"):
    return ApiError(ERR_ALREADY_TERMINAL, 409, msg)
