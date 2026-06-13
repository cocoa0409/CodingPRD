"""Domain error classes and the complete error-id catalog (PRD §5 / scaffold §1.6)."""
from __future__ import annotations


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- error-id constants (verbatim from the scaffold/PRD catalog) --------------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"               # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                           # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                           # 404
ERR_FK_NOT_FOUND = "ERR_FK_NOT_FOUND"                     # 422
ERR_INVALID_STATE = "ERR_INVALID_STATE"                   # 409
ERR_ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"             # 409
ERR_SOD_VIOLATION = "ERR_SOD_VIOLATION"                   # 403
ERR_PHOTO_INVALID = "ERR_PHOTO_INVALID"                   # 422
ERR_GUARDIAN_CONSENT_REQUIRED = "ERR_GUARDIAN_CONSENT_REQUIRED"  # 422
ERR_NAME_CHANGE_EVIDENCE_REQUIRED = "ERR_NAME_CHANGE_EVIDENCE_REQUIRED"  # 422
ERR_FACILITY_SLOT_CONFLICT = "ERR_FACILITY_SLOT_CONFLICT"  # 409
ERR_COUNTER_SLOT_CONFLICT = "ERR_COUNTER_SLOT_CONFLICT"    # 409
ERR_INVALID_INTERVAL = "ERR_INVALID_INTERVAL"             # 422
ERR_DUPLICATE_URGENT_APPOINTMENT = "ERR_DUPLICATE_URGENT_APPOINTMENT"  # 409
ERR_PAYMENT_AMOUNT_MISMATCH = "ERR_PAYMENT_AMOUNT_MISMATCH"  # 422
ERR_FEE_UNPAID = "ERR_FEE_UNPAID"                         # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                   # 412
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"               # 400
ERR_VALIDATION = "ERR_VALIDATION"                         # 422


# --- convenience raisers ------------------------------------------------------
def unauth(msg: str = "Authentication required"):
    raise APIError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg: str = "Role not permitted for this endpoint"):
    raise APIError(ERR_FORBIDDEN, 403, msg)


def not_found(what: str = "resource"):
    raise APIError(ERR_NOT_FOUND, 404, f"{what} not found")


def fk_not_found(what: str = "referenced resource"):
    raise APIError(ERR_FK_NOT_FOUND, 422, f"{what} does not exist")


def invalid_request(msg: str = "Invalid request"):
    raise APIError(ERR_INVALID_REQUEST, 400, msg)


def invalid_state(msg: str = "Invalid state for this transition"):
    raise APIError(ERR_INVALID_STATE, 409, msg)


def already_terminal(msg: str = "Resource is terminal"):
    raise APIError(ERR_ALREADY_TERMINAL, 409, msg)


def validation_error(msg: str = "Field value out of range"):
    raise APIError(ERR_VALIDATION, 422, msg)
