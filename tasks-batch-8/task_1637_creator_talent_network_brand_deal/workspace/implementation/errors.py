"""Error classes and error-ID constants, taken from the scaffold error catalog."""


class ApiError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- error id constants (from scaffold `errors` table) ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                    # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                                # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                # 404
ERR_VALIDATION = "ERR_VALIDATION"                              # 400
ERR_STALE_VERSION = "ERR_STALE_VERSION"                        # 412
ERR_ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"                  # 409
ERR_INVALID_STATE = "ERR_INVALID_STATE"                        # 409
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"        # 403
ERR_CREATOR_COMPLIANCE_SUSPENDED = "ERR_CREATOR_COMPLIANCE_SUSPENDED"  # 422
ERR_DISCLOSURE_NOT_PASSED = "ERR_DISCLOSURE_NOT_PASSED"        # 409
ERR_EXCLUSIVITY_CONFLICT = "ERR_EXCLUSIVITY_CONFLICT"          # 409
ERR_PUBLISH_GAP_VIOLATION = "ERR_PUBLISH_GAP_VIOLATION"        # 409
ERR_DELIVERABLE_COUNT_EXCEEDED = "ERR_DELIVERABLE_COUNT_EXCEEDED"  # 422
ERR_REVISION_LIMIT_EXCEEDED = "ERR_REVISION_LIMIT_EXCEEDED"    # 422
ERR_RESHOOT_LIMIT_EXCEEDED = "ERR_RESHOOT_LIMIT_EXCEEDED"      # 422
ERR_NEGOTIATION_LIMIT_EXCEEDED = "ERR_NEGOTIATION_LIMIT_EXCEEDED"  # 422
ERR_BRIEF_SLOTS_FULL = "ERR_BRIEF_SLOTS_FULL"                  # 422
ERR_PITCH_REQUIREMENTS_NOT_MET = "ERR_PITCH_REQUIREMENTS_NOT_MET"  # 422
ERR_DUPLICATE_REPORT_PERIOD = "ERR_DUPLICATE_REPORT_PERIOD"    # 422
ERR_INVOICE_ALREADY_EXISTS = "ERR_INVOICE_ALREADY_EXISTS"      # 409
ERR_ACTIVE_DEALS_EXIST = "ERR_ACTIVE_DEALS_EXIST"              # 422
ERR_SUBMISSION_WINDOW_CLOSED = "ERR_SUBMISSION_WINDOW_CLOSED"  # 422
ERR_PUBLISH_WINDOW_VIOLATION = "ERR_PUBLISH_WINDOW_VIOLATION"  # 422
ERR_PAYOUT_NOT_DUE = "ERR_PAYOUT_NOT_DUE"                      # 422
ERR_CREATOR_NOT_ACTIVE = "ERR_CREATOR_NOT_ACTIVE"              # 422
ERR_BRAND_SUSPENDED = "ERR_BRAND_SUSPENDED"                    # 422
ERR_BRAND_CREDIT_HOLD = "ERR_BRAND_CREDIT_HOLD"                # 402
ERR_BRIEF_BUDGET_EXCEEDED = "ERR_BRIEF_BUDGET_EXCEEDED"        # 422
ERR_PAYMENT_AMOUNT_MISMATCH = "ERR_PAYMENT_AMOUNT_MISMATCH"    # 422


def unauthenticated(msg="Missing/invalid X-User-Role or X-User-ID, or unknown role"):
    return ApiError(ERR_UNAUTHENTICATED, msg, 401)


def forbidden(msg="Role not allowed on endpoint, or caller does not own the resource"):
    return ApiError(ERR_FORBIDDEN, msg, 403)


def not_found(msg="Path resource id does not exist"):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def validation(msg="Missing required field, invalid enum, or invalid range"):
    return ApiError(ERR_VALIDATION, msg, 400)


def stale_version(msg="expected version does not match the parent entity's current version"):
    return ApiError(ERR_STALE_VERSION, msg, 412)


def already_terminal(msg="Action attempted from a terminal state"):
    return ApiError(ERR_ALREADY_TERMINAL, msg, 409)


def invalid_state(msg="Action attempted from a state the transition does not allow"):
    return ApiError(ERR_INVALID_STATE, msg, 409)
