"""Error classes and error ID constants for the Legal Matter Budgeting API."""


class ApiError(Exception):
    """Exception carrying an error_id, message, and HTTP status."""

    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- Error catalog (SCAFFOLD §1.6 / PRD §5) ---
ERR_MISSING_HEADERS = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"   # 400
ERR_FORBIDDEN_FOR_ROLE = "ERR_FORBIDDEN_FOR_ROLE"                    # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                      # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                          # 400
ERR_INVALID_STATE_TRANSITION = "ERR_INVALID_STATE_TRANSITION"        # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                              # 412
ERR_MATTER_NOT_OPEN = "ERR_MATTER_NOT_OPEN"                          # 409
ERR_CLIENT_NOT_ACTIVE = "ERR_CLIENT_NOT_ACTIVE"                      # 409
ERR_PERIOD_CLOSED = "ERR_PERIOD_CLOSED"                              # 409
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"              # 409
ERR_ARRANGEMENT_FIELDS_INCOMPLETE = "ERR_ARRANGEMENT_FIELDS_INCOMPLETE"  # 422
ERR_ARRANGEMENT_ALREADY_ACTIVE = "ERR_ARRANGEMENT_ALREADY_ACTIVE"    # 409
ERR_TASK_CODE_NOT_BUDGETED = "ERR_TASK_CODE_NOT_BUDGETED"            # 409
ERR_WRITE_DOWN_ENTRIES_INVALID = "ERR_WRITE_DOWN_ENTRIES_INVALID"    # 422
ERR_WRITE_DOWN_ENTRY_STATE = "ERR_WRITE_DOWN_ENTRY_STATE"            # 422
ERR_WRITE_DOWN_AMOUNT_INVALID = "ERR_WRITE_DOWN_AMOUNT_INVALID"      # 422
ERR_AMENDMENT_NEGATIVE_BUDGET = "ERR_AMENDMENT_NEGATIVE_BUDGET"      # 422
ERR_AMENDMENT_AUTHORITY_EXCEEDED = "ERR_AMENDMENT_AUTHORITY_EXCEEDED"  # 403
ERR_AMENDMENT_SUPERSEDE_INVALID = "ERR_AMENDMENT_SUPERSEDE_INVALID"  # 409
ERR_MATTER_HAS_OPEN_WIP = "ERR_MATTER_HAS_OPEN_WIP"                  # 409
ERR_MATTER_HAS_PENDING_WRITE_DOWNS = "ERR_MATTER_HAS_PENDING_WRITE_DOWNS"  # 409
ERR_MATTER_HAS_PENDING_AMENDMENTS = "ERR_MATTER_HAS_PENDING_AMENDMENTS"  # 409
ERR_MATTER_COLLAR_UNSETTLED = "ERR_MATTER_COLLAR_UNSETTLED"          # 409
ERR_MATTER_ACCRUAL_OUTSTANDING = "ERR_MATTER_ACCRUAL_OUTSTANDING"    # 409
ERR_CLIENT_HAS_OPEN_MATTERS = "ERR_CLIENT_HAS_OPEN_MATTERS"          # 409
ERR_REOPEN_WINDOW_CLOSED = "ERR_REOPEN_WINDOW_CLOSED"                # 409
ERR_PHASE_HAS_ACTUALS = "ERR_PHASE_HAS_ACTUALS"                      # 409
ERR_PHASE_HAS_PENDING_AMENDMENT = "ERR_PHASE_HAS_PENDING_AMENDMENT"  # 409
ERR_PHASE_NOT_AMENDABLE = "ERR_PHASE_NOT_AMENDABLE"                  # 409


def err_missing_headers(msg="X-User-ID or X-User-Role header missing or malformed"):
    return ApiError(ERR_MISSING_HEADERS, msg, 400)


def err_forbidden(msg="Role lacks permission for the endpoint"):
    return ApiError(ERR_FORBIDDEN_FOR_ROLE, msg, 403)


def err_not_found(msg="Resource id does not exist within the firm scope"):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def err_invalid_request(msg="Malformed body, non-positive amounts, zero/negative hours, or invalid enum value"):
    return ApiError(ERR_INVALID_REQUEST, msg, 400)


def err_invalid_state(msg="Generic state precondition failure"):
    return ApiError(ERR_INVALID_STATE_TRANSITION, msg, 409)


def err_stale_version(msg="OCC mismatch on expected_matter_version"):
    return ApiError(ERR_STALE_VERSION, msg, 412)
