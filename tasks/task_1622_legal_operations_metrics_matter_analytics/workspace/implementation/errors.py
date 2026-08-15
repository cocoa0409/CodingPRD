"""Error catalog — IDs and HTTP statuses from SCAFFOLD Table 6 / PRD section 5."""

ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                        # 403
ERR_SOD_VIOLATION = "ERR_SOD_VIOLATION"                # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"                # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                # 412
ERR_PERIOD_CLOSED = "ERR_PERIOD_CLOSED"                # 409
ERR_PERIOD_NOT_HARD_CLOSED = "ERR_PERIOD_NOT_HARD_CLOSED"  # 409
ERR_PERIOD_OVERLAP = "ERR_PERIOD_OVERLAP"              # 422
ERR_TAXONOMY_MISMATCH = "ERR_TAXONOMY_MISMATCH"        # 422
ERR_PARENT_MISMATCH = "ERR_PARENT_MISMATCH"            # 422
ERR_ENTITY_INACTIVE = "ERR_ENTITY_INACTIVE"            # 422
ERR_DUPLICATE = "ERR_DUPLICATE"                        # 409
ERR_INVALID_AMOUNT = "ERR_INVALID_AMOUNT"              # 422
ERR_BUDGET_OVERRUN_EXCEEDED = "ERR_BUDGET_OVERRUN_EXCEEDED"  # 422
ERR_NO_ACTIVE_ASSIGNMENT = "ERR_NO_ACTIVE_ASSIGNMENT"  # 422
ERR_PERIOD_NOT_CLOSABLE = "ERR_PERIOD_NOT_CLOSABLE"    # 422
ERR_REOPEN_LIMIT = "ERR_REOPEN_LIMIT"                  # 422
ERR_CAPACITY_EXCEEDED = "ERR_CAPACITY_EXCEEDED"        # 422
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"            # 400


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def not_found(what="resource"):
    return ApiError(ERR_NOT_FOUND, 404, "Referenced %s does not exist" % what)


def invalid_state(msg="Target resource not in a state that permits the requested transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)
