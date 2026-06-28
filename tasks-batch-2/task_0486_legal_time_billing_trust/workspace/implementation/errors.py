"""Error classes and error-id constants for the Legal Time/Billing/Trust API."""


class ApiError(Exception):
    """An error carrying a machine-readable error_id and an HTTP status code."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error id -> http status. (See PRD §5 / scaffold §1.6.)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"              # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_CODE_KIND_MISMATCH = "ERR_CODE_KIND_MISMATCH"      # 422
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_STALE_INVOICE_VERSION = "ERR_STALE_INVOICE_VERSION"  # 412
ERR_SOD_SAME_ACTOR = "ERR_SOD_SAME_ACTOR"             # 403
ERR_CONFLICT_NOT_CLEARED = "ERR_CONFLICT_NOT_CLEARED"  # 409
ERR_TRUST_OVERDRAW = "ERR_TRUST_OVERDRAW"             # 422
ERR_COLLECTIONS_TOO_EARLY = "ERR_COLLECTIONS_TOO_EARLY"  # 409
ERR_OVERPAYMENT = "ERR_OVERPAYMENT"                   # 422
ERR_PARTIAL_WRITEOFF = "ERR_PARTIAL_WRITEOFF"         # 422
ERR_MATTER_HAS_OPEN_BALANCE = "ERR_MATTER_HAS_OPEN_BALANCE"  # 409
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"           # 400
ERR_TIMEKEEPER_INACTIVE = "ERR_TIMEKEEPER_INACTIVE"   # 422
ERR_DUPLICATE_CODE = "ERR_DUPLICATE_CODE"             # 409
ERR_VALIDATION_LIMIT = "ERR_VALIDATION_LIMIT"         # 422
ERR_LEDGER_ACCOUNT_MISMATCH = "ERR_LEDGER_ACCOUNT_MISMATCH"  # 422
ERR_TIME_OVERLAP = "ERR_TIME_OVERLAP"                 # 409
ERR_HOLD_OVERLAP = "ERR_HOLD_OVERLAP"                 # 409


def unauthenticated(msg="Missing X-User-ID or X-User-Role header."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg="Role not permitted for this operation."):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_found(msg="Referenced resource does not exist."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def code_kind_mismatch(msg="Referenced code is of the wrong kind."):
    return ApiError(ERR_CODE_KIND_MISMATCH, 422, msg)


def invalid_state(msg="Target resource is not in a valid state for this operation."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_invoice_version(msg="expected_invoice_version does not match the current invoice version."):
    return ApiError(ERR_STALE_INVOICE_VERSION, 412, msg)


def sod_same_actor(msg="Segregation of duties: approver/reverser may not equal the initiator."):
    return ApiError(ERR_SOD_SAME_ACTOR, 403, msg)


def conflict_not_cleared(msg="Matter's latest conflict check is not CLEAR or WAIVED."):
    return ApiError(ERR_CONFLICT_NOT_CLEARED, 409, msg)


def trust_overdraw(msg="Disbursement/sweep would drive a client trust ledger below zero."):
    return ApiError(ERR_TRUST_OVERDRAW, 422, msg)


def collections_too_early(msg="Cannot send to collections before the grace period has elapsed."):
    return ApiError(ERR_COLLECTIONS_TOO_EARLY, 409, msg)


def overpayment(msg="Payment or sweep amount exceeds the invoice remaining balance."):
    return ApiError(ERR_OVERPAYMENT, 422, msg)


def partial_writeoff(msg="Write-off amount must equal the full remaining balance."):
    return ApiError(ERR_PARTIAL_WRITEOFF, 422, msg)


def matter_has_open_balance(msg="Matter has open WIP or outstanding A/R."):
    return ApiError(ERR_MATTER_HAS_OPEN_BALANCE, 409, msg)


def invalid_request(msg="Missing or invalid request body field."):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def timekeeper_inactive(msg="Timekeeper is not active."):
    return ApiError(ERR_TIMEKEEPER_INACTIVE, 422, msg)


def duplicate_code(msg="Billing code already exists."):
    return ApiError(ERR_DUPLICATE_CODE, 409, msg)


def validation_limit(msg="Pagination limit/offset out of bounds."):
    return ApiError(ERR_VALIDATION_LIMIT, 422, msg)


def ledger_account_mismatch(msg="Trust ledger belongs to a different client than the invoice."):
    return ApiError(ERR_LEDGER_ACCOUNT_MISMATCH, 422, msg)


def time_overlap(msg="Time entry interval overlaps an existing entry for this timekeeper."):
    return ApiError(ERR_TIME_OVERLAP, 409, msg)


def hold_overlap(msg="Retainer hold interval overlaps an active hold on this ledger."):
    return ApiError(ERR_HOLD_OVERLAP, 409, msg)
