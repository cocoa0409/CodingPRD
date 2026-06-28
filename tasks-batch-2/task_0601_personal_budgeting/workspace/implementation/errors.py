"""Error classes and error-id constants for the Personal Budgeting API.

Error catalog — PRD §5 / scaffold §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                  # 400
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                  # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                              # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                              # 404
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"          # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"                      # 409
ERR_ACCOUNT_ARCHIVED = "ERR_ACCOUNT_ARCHIVED"                # 409
ERR_HOUSEHOLD_FROZEN = "ERR_HOUSEHOLD_FROZEN"                # 409
ERR_CATEGORY_PERIOD_MISMATCH = "ERR_CATEGORY_PERIOD_MISMATCH"  # 409
ERR_PENDING_TRANSACTIONS_EXIST = "ERR_PENDING_TRANSACTIONS_EXIST"  # 409
ERR_DUPLICATE_RESOURCE = "ERR_DUPLICATE_RESOURCE"            # 409
ERR_BILL_SLOT_CONFLICT = "ERR_BILL_SLOT_CONFLICT"            # 409
ERR_INSUFFICIENT_ENVELOPE = "ERR_INSUFFICIENT_ENVELOPE"      # 422
ERR_BUDGET_NOT_ZERO_BASED = "ERR_BUDGET_NOT_ZERO_BASED"      # 422
ERR_STALE_HOUSEHOLD = "ERR_STALE_HOUSEHOLD"                  # 412
ERR_GOAL_TARGET_BELOW_FUNDED = "ERR_GOAL_TARGET_BELOW_FUNDED"  # 422


def invalid_request(msg="Invalid request body"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def unauthenticated(msg="Missing or unrecognized role"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Role not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def reference_not_found(msg="Referenced resource not found"):
    return ApiError(ERR_REFERENCE_NOT_FOUND, 404, msg)


def invalid_state(msg="Resource is not in the required state for this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)
