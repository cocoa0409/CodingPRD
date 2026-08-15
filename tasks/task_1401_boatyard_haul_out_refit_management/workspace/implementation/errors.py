"""Error classes and error ID constants (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_OWNERSHIP_MISMATCH = "ERR_OWNERSHIP_MISMATCH"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_VALIDATION = "ERR_VALIDATION"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"
ERR_ENV_MORATORIUM = "ERR_ENV_MORATORIUM"
ERR_LIFT_CAPACITY_EXCEEDED = "ERR_LIFT_CAPACITY_EXCEEDED"
ERR_INSURANCE_MISSING = "ERR_INSURANCE_MISSING"
ERR_OPEN_COMPLIANCE_HOLD = "ERR_OPEN_COMPLIANCE_HOLD"
ERR_LIFT_SLOT_CONFLICT = "ERR_LIFT_SLOT_CONFLICT"
ERR_STANDS_EXHAUSTED = "ERR_STANDS_EXHAUSTED"
ERR_STAND_ASSIGNMENT_MISSING = "ERR_STAND_ASSIGNMENT_MISSING"
ERR_OWNER_PARTS_PROHIBITED = "ERR_OWNER_PARTS_PROHIBITED"
ERR_WINTERIZATION_WINDOW = "ERR_WINTERIZATION_WINDOW"
ERR_SUBCONTRACTOR_NOT_ALLOWED = "ERR_SUBCONTRACTOR_NOT_ALLOWED"
ERR_DUPLICATE_ACTIVE_JOB = "ERR_DUPLICATE_ACTIVE_JOB"
ERR_JOB_NOT_READY_FOR_SPLASH = "ERR_JOB_NOT_READY_FOR_SPLASH"
ERR_DEPOSIT_SHORTFALL = "ERR_DEPOSIT_SHORTFALL"


def unauthenticated(msg="Missing or invalid X-User-ID / X-User-Role headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="Role not permitted for this endpoint"):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def ownership(msg="Owner may act only on resources owned by them"):
    return ApiError(ERR_OWNERSHIP_MISMATCH, 403, msg)


def not_found(msg="Referenced id does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def validation(msg):
    return ApiError(ERR_VALIDATION, 400, msg)


def stale(msg="Expected version does not match current version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def invalid_state(msg="Entity state does not allow the requested transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def already_terminal(msg="Entity is in a terminal state"):
    return ApiError(ERR_ALREADY_TERMINAL, 409, msg)
