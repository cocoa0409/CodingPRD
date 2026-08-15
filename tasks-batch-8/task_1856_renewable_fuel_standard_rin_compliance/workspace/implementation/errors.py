"""Error classes and error ID constants for the RFS RIN compliance API."""


class ApiError(Exception):
    """Carries error_id, message, and http_status through to the error handler."""

    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- Error ID constants (from SCAFFOLD error catalog) ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"              # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                          # 403
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                          # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"              # 400
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"      # 422
ERR_STALE_VERSION = "ERR_STALE_VERSION"                  # 412
ERR_INVALID_STATE = "ERR_INVALID_STATE"                  # 409
ERR_VENDOR_NOT_APPROVED = "ERR_VENDOR_NOT_APPROVED"      # 409
ERR_RIN_INVALIDATED = "ERR_RIN_INVALIDATED"              # 409
ERR_ATTEST_NOT_CLEAN = "ERR_ATTEST_NOT_CLEAN"            # 409
ERR_D_CODE_NOT_ELIGIBLE = "ERR_D_CODE_NOT_ELIGIBLE"      # 409
ERR_ENGAGEMENT_WINDOW_OVERLAP = "ERR_ENGAGEMENT_WINDOW_OVERLAP"  # 409
ERR_PRICE_WINDOW_OVERLAP = "ERR_PRICE_WINDOW_OVERLAP"    # 409
ERR_INVALID_VINTAGE = "ERR_INVALID_VINTAGE"              # 409
ERR_DEADLINE_PASSED = "ERR_DEADLINE_PASSED"              # 409
ERR_VERIFICATION_WINDOW_EXPIRED = "ERR_VERIFICATION_WINDOW_EXPIRED"  # 409
ERR_RETENTION_ACTIVE = "ERR_RETENTION_ACTIVE"            # 409
ERR_SEPARATION_EXCEEDS_ATTACHED = "ERR_SEPARATION_EXCEEDS_ATTACHED"  # 409
ERR_INSUFFICIENT_RINS = "ERR_INSUFFICIENT_RINS"          # 409
ERR_CARRYOVER_CAP_EXCEEDED = "ERR_CARRYOVER_CAP_EXCEEDED"  # 409
ERR_YEAR_NOT_FINALIZABLE = "ERR_YEAR_NOT_FINALIZABLE"    # 409


def unauthenticated(msg="Missing or invalid authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, msg, 401)


def forbidden(msg="Role not permitted for this endpoint"):
    return ApiError(ERR_FORBIDDEN, msg, 403)


def segregation(msg="Segregation of duties violation"):
    return ApiError(ERR_SEGREGATION_OF_DUTIES, msg, 403)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def invalid_request(msg="Invalid request"):
    return ApiError(ERR_INVALID_REQUEST, msg, 400)


def reference_not_found(msg="Referenced resource not found"):
    return ApiError(ERR_REFERENCE_NOT_FOUND, msg, 422)


def stale_version(msg="Stale obligation year version"):
    return ApiError(ERR_STALE_VERSION, msg, 412)


def invalid_state(msg="Resource is not in a valid state for this operation"):
    return ApiError(ERR_INVALID_STATE, msg, 409)


def vendor_not_approved(msg="Vendor is not APPROVED"):
    return ApiError(ERR_VENDOR_NOT_APPROVED, msg, 409)


def rin_invalidated(msg="Operation targets an INVALIDATED lot or trade"):
    return ApiError(ERR_RIN_INVALIDATED, msg, 409)


def attest_not_clean(msg="ANNUAL report requires a CLOSED_CLEAN attest engagement"):
    return ApiError(ERR_ATTEST_NOT_CLEAN, msg, 409)


def d_code_not_eligible(msg="D-code is not eligible for the batch category"):
    return ApiError(ERR_D_CODE_NOT_ELIGIBLE, msg, 409)


def engagement_window_overlap(msg="Fieldwork window overlaps another engagement for the same auditor"):
    return ApiError(ERR_ENGAGEMENT_WINDOW_OVERLAP, msg, 409)


def price_window_overlap(msg="Effective window overlaps an existing quote for the same account, D-code, and vintage"):
    return ApiError(ERR_PRICE_WINDOW_OVERLAP, msg, 409)


def invalid_vintage(msg="Vintage year outside the allowed window"):
    return ApiError(ERR_INVALID_VINTAGE, msg, 409)


def deadline_passed(msg="Retirement deadline has passed"):
    return ApiError(ERR_DEADLINE_PASSED, msg, 409)


def verification_window_expired(msg="Verification window expired"):
    return ApiError(ERR_VERIFICATION_WINDOW_EXPIRED, msg, 409)


def retention_active(msg="A targeted record is still within its retention window"):
    return ApiError(ERR_RETENTION_ACTIVE, msg, 409)


def separation_exceeds_attached(msg="Blended gallons exceed the lot's attached quantity"):
    return ApiError(ERR_SEPARATION_EXCEEDS_ATTACHED, msg, 409)


def insufficient_rins(msg="Insufficient RINs"):
    return ApiError(ERR_INSUFFICIENT_RINS, msg, 409)


def carryover_cap_exceeded(msg="Prior-vintage RINs exceed the carryover cap"):
    return ApiError(ERR_CARRYOVER_CAP_EXCEEDED, msg, 409)


def year_not_finalizable(msg="Year cannot be finalized"):
    return ApiError(ERR_YEAR_NOT_FINALIZABLE, msg, 409)
