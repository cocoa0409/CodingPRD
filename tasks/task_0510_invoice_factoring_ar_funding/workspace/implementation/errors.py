"""Error classes and error-id constants for the invoice-factoring API."""


class ApiError(Exception):
    """A business / validation error carrying the scaffold error_id + HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalog (§1.6 / PRD §5) ---------------------------------------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                  # 403
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"            # 422
ERR_DUPLICATE_INVOICE_NUMBER = "ERR_DUPLICATE_INVOICE_NUMBER"  # 409
ERR_DUPLICATE_RELATIONSHIP = "ERR_DUPLICATE_RELATIONSHIP"      # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                # 412
ERR_INVALID_STATE = "ERR_INVALID_STATE"                # 409
ERR_NOTICE_NOT_SENT = "ERR_NOTICE_NOT_SENT"            # 409
ERR_PARTY_NOT_APPROVED = "ERR_PARTY_NOT_APPROVED"      # 409
ERR_VERIFICATION_MISMATCH = "ERR_VERIFICATION_MISMATCH"  # 409
ERR_FUNDING_BLOCKED = "ERR_FUNDING_BLOCKED"            # 409
ERR_CONCENTRATION_EXCEEDED = "ERR_CONCENTRATION_EXCEEDED"  # 409
ERR_DEBTOR_CEILING_EXCEEDED = "ERR_DEBTOR_CEILING_EXCEEDED"  # 409
ERR_CREDIT_LIMIT_EXCEEDED = "ERR_CREDIT_LIMIT_EXCEEDED"  # 409
ERR_NON_RECOURSE_NO_BUYBACK = "ERR_NON_RECOURSE_NO_BUYBACK"  # 409
ERR_RECOURSE_GRACE_ACTIVE = "ERR_RECOURSE_GRACE_ACTIVE"  # 409
ERR_WRITEOFF_NOT_ELIGIBLE = "ERR_WRITEOFF_NOT_ELIGIBLE"  # 409
ERR_CLIENT_HAS_OUTSTANDING = "ERR_CLIENT_HAS_OUTSTANDING"  # 409
ERR_OVERPAYMENT = "ERR_OVERPAYMENT"                    # 409


def unauthenticated(msg="Missing or invalid authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="Role not permitted for this operation"):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid request body"):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def invalid_state(msg="Requested transition not defined from current state"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_version(msg="expected_client_version does not match current Client.version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)
