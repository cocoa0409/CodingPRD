"""Error classes and error-ID constants.

Every error_id and HTTP status is taken verbatim from PRD §5 (Error Code
Catalogue) and SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- auth / existence / request ---
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"  # 400
ERR_FORBIDDEN_FOR_ROLE = "ERR_FORBIDDEN_FOR_ROLE"                                            # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                                              # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                                                  # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"                                                      # 409

# --- eligibility / size ---
ERR_INELIGIBLE_BUSINESS = "ERR_INELIGIBLE_BUSINESS"                                          # 409
ERR_SIZE_STANDARD_EXCEEDED = "ERR_SIZE_STANDARD_EXCEEDED"                                    # 409
ERR_NO_PROCEEDS = "ERR_NO_PROCEEDS"                                                          # 409
ERR_PROCEEDS_MISMATCH = "ERR_PROCEEDS_MISMATCH"                                              # 422

# --- form package / underwriting ---
ERR_FORM_INCOMPLETE = "ERR_FORM_INCOMPLETE"                                                  # 409
ERR_FORM_PACKAGE_NOT_CLEARED = "ERR_FORM_PACKAGE_NOT_CLEARED"                                # 409
ERR_COLLATERAL_SHORTFALL = "ERR_COLLATERAL_SHORTFALL"                                        # 409
ERR_NO_CREDIT_MEMO = "ERR_NO_CREDIT_MEMO"                                                    # 409
ERR_MEMO_NOT_APPROVABLE = "ERR_MEMO_NOT_APPROVABLE"                                          # 409

# --- segregation of duties ---
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"                                      # 409

# --- disbursement / closing ---
ERR_NOT_AUTHORIZED_FOR_DISBURSAL = "ERR_NOT_AUTHORIZED_FOR_DISBURSAL"                        # 409
ERR_DRAW_WINDOW_OVERLAP = "ERR_DRAW_WINDOW_OVERLAP"                                          # 409
ERR_OVER_DISBURSEMENT = "ERR_OVER_DISBURSEMENT"                                              # 409
ERR_NOT_FULLY_DISBURSED = "ERR_NOT_FULLY_DISBURSED"                                          # 409

# --- secondary market ---
ERR_SALE_PRINCIPAL_MISMATCH = "ERR_SALE_PRINCIPAL_MISMATCH"                                  # 422
ERR_GUARANTY_NOT_SELLABLE = "ERR_GUARANTY_NOT_SELLABLE"                                      # 409
ERR_STALE_APPLICATION_VERSION = "ERR_STALE_APPLICATION_VERSION"                              # 412

# --- servicing / 1502 ---
ERR_PERIOD_OUT_OF_ORDER = "ERR_PERIOD_OUT_OF_ORDER"                                          # 409
ERR_PRINCIPAL_OVERPAY = "ERR_PRINCIPAL_OVERPAY"                                              # 422

# --- default / liquidation / purchase ---
ERR_NOT_DELINQUENT_ENOUGH = "ERR_NOT_DELINQUENT_ENOUGH"                                      # 409
ERR_NOT_DEFAULTED = "ERR_NOT_DEFAULTED"                                                      # 409


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
