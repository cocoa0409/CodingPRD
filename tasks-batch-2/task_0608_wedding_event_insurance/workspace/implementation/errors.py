"""Error classes and the error catalog (PRD §5)."""


class ApiError(Exception):
    """Carries an error_id, message, and http_status, rendered into the error envelope."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http status (PRD §5 Error Code Catalogue).
ERROR_STATUS = {
    "ERR_MISSING_USER_CONTEXT": 401,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    "ERR_NOT_POLICY_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_POLICY_NOT_QUOTED": 409,
    "ERR_POLICY_NOT_BOUND": 409,
    "ERR_POLICY_NOT_IN_FORCE": 409,
    "ERR_POLICY_NOT_CANCELLABLE": 409,
    "ERR_PREMIUM_UNPAID": 409,
    "ERR_PREMIUM_ALREADY_PAID": 409,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
    "ERR_EVENT_NOT_ENDED": 409,
    "ERR_OPEN_CLAIM_BLOCKS_CANCEL": 409,
    "ERR_NO_EVENT_PROFILE": 422,
    "ERR_NO_COVERAGE_SELECTED": 422,
    "ERR_SINGLE_EVENT_MULTIPLE_PROFILES": 422,
    "ERR_INVALID_EVENT_WINDOW": 422,
    "ERR_VENUE_VENDOR_REQUIRED": 422,
    "ERR_PRODUCT_RETIRED": 422,
    "ERR_DUPLICATE_COVERAGE": 409,
    "ERR_PROTECTED_VENDOR_NOT_ALLOWED": 422,
    "ERR_LIQUOR_REQUIRES_ALCOHOL": 422,
    "ERR_CERTIFICATE_NOT_REQUESTED": 409,
    "ERR_CERTIFICATE_NOT_ISSUED": 409,
    "ERR_NO_LIABILITY_COVERAGE": 422,
    "ERR_ENDORSEMENT_NOT_DRAFT": 409,
    "ERR_STALE_POLICY_VERSION": 412,
    "ERR_CLAIM_NOT_SUBMITTED": 409,
    "ERR_CLAIM_NOT_INFO_REQUESTED": 409,
    "ERR_CLAIM_NOT_APPROVED": 409,
    "ERR_COVERAGE_NOT_ACTIVE": 409,
    "ERR_INSUFFICIENT_DOCUMENTATION": 422,
    "ERR_NO_NEW_DOCUMENTATION": 422,
    "ERR_REVISION_CAP_EXCEEDED": 422,
    "ERR_VENDOR_NOT_DEFAULTED": 422,
    "ERR_BOUND_AFTER_CUTOFF": 422,
    "ERR_LANDFALL_OUTSIDE_WINDOW": 422,
    "ERR_FORCE_MAJEURE_NOT_COVERED": 422,
    "ERR_COVERAGE_LIMIT_EXCEEDED": 422,
    "ERR_VENDOR_NOT_SOLVENT": 409,
    "ERR_VENDOR_NOT_FLAGGED": 409,
    "ERR_PERIL_NOT_WATCH": 409,
    "ERR_PERIL_NOT_ACTIVE": 409,
    "ERR_INVALID_STATE": 409,
}


def err(error_id, message=None):
    """Build an ApiError using the catalog's status for the given id."""
    return ApiError(error_id, ERROR_STATUS.get(error_id, 400), message)
