"""Error classes and error-ID constants.

Every error_id and HTTP status is taken verbatim from PRD §5 (Error Code
Catalogue) and SCAFFOLD Table 6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- auth / existence / request / state / OCC ---
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"  # 400
ERR_FORBIDDEN_FOR_ROLE = "ERR_FORBIDDEN_FOR_ROLE"                                            # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                                              # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                                                  # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"                                                      # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                                                      # 412

# --- credit application ---
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"                                      # 403
ERR_APPROVED_EXCEEDS_REQUESTED = "ERR_APPROVED_EXCEEDS_REQUESTED"                            # 409
ERR_SCORE_BELOW_FLOOR = "ERR_SCORE_BELOW_FLOOR"                                              # 409

# --- lease book / fund ---
ERR_TRAC_RESIDUAL_REQUIRED = "ERR_TRAC_RESIDUAL_REQUIRED"                                    # 409
ERR_NO_EQUIPMENT = "ERR_NO_EQUIPMENT"                                                        # 409
ERR_VENDOR_NOT_APPROVED = "ERR_VENDOR_NOT_APPROVED"                                          # 409
ERR_NOT_BOOKED = "ERR_NOT_BOOKED"                                                            # 409
ERR_CREDIT_LIMIT_EXCEEDED = "ERR_CREDIT_LIMIT_EXCEEDED"                                      # 409

# --- end of term ---
ERR_TERM_NOT_COMPLETE = "ERR_TERM_NOT_COMPLETE"                                              # 409
ERR_LEASE_NOT_END_OF_TERM = "ERR_LEASE_NOT_END_OF_TERM"                                      # 409
ERR_BUYOUT_NOT_PAID = "ERR_BUYOUT_NOT_PAID"                                                  # 409
ERR_OUTSTANDING_BALANCE = "ERR_OUTSTANDING_BALANCE"                                          # 409
ERR_ELECTION_NOT_EXERCISED = "ERR_ELECTION_NOT_EXERCISED"                                    # 409
ERR_ELECTION_MISMATCH = "ERR_ELECTION_MISMATCH"                                              # 409

# --- billing / payments ---
ERR_INVOICE_HAS_PAYMENTS = "ERR_INVOICE_HAS_PAYMENTS"                                        # 409
ERR_PAYMENT_EXCEEDS_DUE = "ERR_PAYMENT_EXCEEDS_DUE"                                          # 409

# --- equipment / serial ---
ERR_DUPLICATE_SERIAL = "ERR_DUPLICATE_SERIAL"                                                # 409
ERR_SERIAL_REUSE_TOO_SOON = "ERR_SERIAL_REUSE_TOO_SOON"                                      # 409

# --- add-on ---
ERR_LEASE_NOT_ACTIVE = "ERR_LEASE_NOT_ACTIVE"                                                # 409

# --- ucc ---
ERR_UCC_OVERLAP = "ERR_UCC_OVERLAP"                                                          # 409
ERR_UCC_WRONG_JURISDICTION = "ERR_UCC_WRONG_JURISDICTION"                                    # 409


# Convenience constructors -----------------------------------------------------

def err(error_id, http_status, message=None):
    return ApiError(error_id, http_status, message)


def missing_header(msg="Missing or invalid user context header"):
    return ApiError(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400, msg)


def forbidden(msg="Role not permitted for this endpoint"):
    return ApiError(ERR_FORBIDDEN_FOR_ROLE, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid request body"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def invalid_state(msg="Resource not in a valid state for this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def conflict(error_id, msg=None):
    return ApiError(error_id, 409, msg or error_id)


def conflict_403(error_id, msg=None):
    """A business-rule rejection that returns HTTP 403 (e.g. segregation of duties)."""
    return ApiError(error_id, 403, msg or error_id)


def stale_version(msg="Lease version does not match expected_lease_version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)
