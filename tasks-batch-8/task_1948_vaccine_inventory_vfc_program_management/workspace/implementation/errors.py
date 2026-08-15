"""Error classes and error ID constants per SCAFFOLD §1.6 / PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error ID constants (exact strings from the scaffold error catalog)
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
ERR_INSUFFICIENT_PERMISSIONS = "ERR_INSUFFICIENT_PERMISSIONS"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STORAGE_UNIT_QUARANTINED = "ERR_STORAGE_UNIT_QUARANTINED"
ERR_LOT_NOT_AVAILABLE = "ERR_LOT_NOT_AVAILABLE"
ERR_LOT_EXPIRED = "ERR_LOT_EXPIRED"
ERR_STOCK_ELIGIBILITY_MISMATCH = "ERR_STOCK_ELIGIBILITY_MISMATCH"
ERR_SCREENING_MISMATCH = "ERR_SCREENING_MISMATCH"
ERR_PATIENT_NOT_VFC_ELIGIBLE_AGE = "ERR_PATIENT_NOT_VFC_ELIGIBLE_AGE"
ERR_UNIT_SITE_MISMATCH = "ERR_UNIT_SITE_MISMATCH"
ERR_INSUFFICIENT_STOCK = "ERR_INSUFFICIENT_STOCK"
ERR_SAME_STOCK_BORROW = "ERR_SAME_STOCK_BORROW"
ERR_PAYBACK_EXCEEDS_BORROWED = "ERR_PAYBACK_EXCEEDS_BORROWED"
ERR_TICKET_HAS_PAYBACK = "ERR_TICKET_HAS_PAYBACK"
ERR_BORROWED_DOSES_CONSUMED = "ERR_BORROWED_DOSES_CONSUMED"
ERR_OVER_RECEIPT = "ERR_OVER_RECEIPT"
ERR_ALLOCATION_MISMATCH = "ERR_ALLOCATION_MISMATCH"
ERR_LINE_ALLOCATION_MISSING = "ERR_LINE_ALLOCATION_MISSING"
ERR_SITE_SUSPENDED_ORDERING = "ERR_SITE_SUSPENDED_ORDERING"
ERR_ACCOUNTABILITY_GAP_UNRESOLVED = "ERR_ACCOUNTABILITY_GAP_UNRESOLVED"
ERR_OPEN_EXCURSION_EXISTS = "ERR_OPEN_EXCURSION_EXISTS"
ERR_OPEN_BORROW_TICKET_EXISTS = "ERR_OPEN_BORROW_TICKET_EXISTS"
ERR_OPEN_AUDIT_EXISTS = "ERR_OPEN_AUDIT_EXISTS"
ERR_EXCURSION_STILL_OPEN = "ERR_EXCURSION_STILL_OPEN"
ERR_EMPTY_ORDER = "ERR_EMPTY_ORDER"
ERR_INVALID_ENUM = "ERR_INVALID_ENUM"


def missing_or_invalid_user_context():
    return ApiError(
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
        "X-User-ID or X-User-Role header missing or syntactically invalid",
        400,
    )


def insufficient_permissions():
    return ApiError(
        ERR_INSUFFICIENT_PERMISSIONS,
        "Role not permitted for this endpoint",
        403,
    )


def not_found(resource: str = "resource"):
    return ApiError(ERR_NOT_FOUND, f"Referenced {resource} id does not exist", 404)


def invalid_request(message: str = "Required field missing, type mismatch, or value out of range"):
    return ApiError(ERR_INVALID_REQUEST, message, 400)


def invalid_enum(message: str = "Enum field carries a value outside its declared constraint set"):
    return ApiError(ERR_INVALID_ENUM, message, 400)


def stale_version():
    return ApiError(
        ERR_STALE_VERSION,
        "expected_<parent>_version does not match the parent's current version",
        412,
    )


def invalid_state(message: str = "Target resource's current state does not permit the requested transition"):
    return ApiError(ERR_INVALID_STATE, message, 409)
