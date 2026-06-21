"""Error classes and error-id constants for the SDU API.

Every error_id and its HTTP status are taken verbatim from PRD section 5 /
SCAFFOLD 1.6. Nothing here is invented.
"""


class ApiError(Exception):
    """Carries an error_id, message, and http_status to the error handler."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalogue (PRD section 5) ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                        # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"            # 400
ERR_FK_MISMATCH = "ERR_FK_MISMATCH"                    # 422
ERR_DUPLICATE_FEIN = "ERR_DUPLICATE_FEIN"              # 409
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"               # 412
ERR_INVALID_AMOUNT = "ERR_INVALID_AMOUNT"             # 422
ERR_BELOW_ENFORCEMENT_THRESHOLD = "ERR_BELOW_ENFORCEMENT_THRESHOLD"  # 422
ERR_PAYEE_ON_HOLD = "ERR_PAYEE_ON_HOLD"               # 409
ERR_NO_ALLOCABLE_ORDER = "ERR_NO_ALLOCABLE_ORDER"     # 409
ERR_NOTHING_TO_ALLOCATE = "ERR_NOTHING_TO_ALLOCATE"   # 409
ERR_ARREARS_OUTSTANDING = "ERR_ARREARS_OUTSTANDING"   # 409
ERR_ENFORCEMENT_ACTIVE = "ERR_ENFORCEMENT_ACTIVE"     # 409
ERR_ORDER_NOT_ACTIVE = "ERR_ORDER_NOT_ACTIVE"         # 409
ERR_OVER_DISBURSEMENT = "ERR_OVER_DISBURSEMENT"       # 409
ERR_IWO_PERIOD_OVERLAP = "ERR_IWO_PERIOD_OVERLAP"     # 409
ERR_MODIFICATION_PERIOD_OVERLAP = "ERR_MODIFICATION_PERIOD_OVERLAP"  # 409


# Convenience raisers ---------------------------------------------------------
def unauthenticated(msg="Missing or unrecognized X-User-Role header"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Role not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Missing or malformed request body"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def fk_mismatch(msg="Body foreign key references an incompatible resource"):
    return ApiError(ERR_FK_MISMATCH, 422, msg)


def duplicate_fein(msg="Employer.fein already exists"):
    return ApiError(ERR_DUPLICATE_FEIN, 409, msg)


def invalid_state(msg="Resource not in a valid state for the requested transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_version(msg="expected_support_order_version does not match current version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def invalid_amount(msg="Amount must be greater than zero"):
    return ApiError(ERR_INVALID_AMOUNT, 422, msg)


def below_threshold(msg="Certified arrears below the statutory enforcement threshold"):
    return ApiError(ERR_BELOW_ENFORCEMENT_THRESHOLD, 422, msg)


def payee_on_hold(msg="CustodialParty.payee_status is HOLD; disbursement cannot be sent"):
    return ApiError(ERR_PAYEE_ON_HOLD, 409, msg)


def no_allocable_order(msg="Obligor has no ACTIVE/MODIFIED support order to allocate against"):
    return ApiError(ERR_NO_ALLOCABLE_ORDER, 409, msg)


def nothing_to_allocate(msg="Remittance distributable_cents is 0"):
    return ApiError(ERR_NOTHING_TO_ALLOCATE, 409, msg)


def arrears_outstanding(msg="Order cannot terminate while arrears principal or interest remain"):
    return ApiError(ERR_ARREARS_OUTSTANDING, 409, msg)


def enforcement_active(msg="Order cannot terminate while an enforcement intercept is pending/active"):
    return ApiError(ERR_ENFORCEMENT_ACTIVE, 409, msg)


def order_not_active(msg="Modification decide/apply requires the linked order to be ACTIVE"):
    return ApiError(ERR_ORDER_NOT_ACTIVE, 409, msg)


def over_disbursement(msg="Disbursement would exceed the allocation slice's distributable total"):
    return ApiError(ERR_OVER_DISBURSEMENT, 409, msg)


def iwo_period_overlap(msg="New IWO interval overlaps an existing non-TERMINATED IWO on the same order"):
    return ApiError(ERR_IWO_PERIOD_OVERLAP, 409, msg)


def modification_period_overlap(msg="New Modification interval overlaps an existing non-REJECTED Modification on the same order"):
    return ApiError(ERR_MODIFICATION_PERIOD_OVERLAP, 409, msg)
