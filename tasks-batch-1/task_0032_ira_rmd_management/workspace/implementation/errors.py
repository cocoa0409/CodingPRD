"""Custom exception class plus the error catalog from PRD §5."""


class APIError(Exception):
    """Raised by handlers; caught by Flask's error_handler and turned into the
    standard error envelope defined in PRD §2.2."""

    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Default messages for each catalog entry. Tests check error_id and http_status;
# the human-readable string is informational.
ERR_MISSING_AUTH = ("ERR_MISSING_AUTH", 401, "X-User-Role header missing or empty.")
ERR_INVALID_ROLE = ("ERR_INVALID_ROLE", 401, "X-User-Role is not a recognized role.")
ERR_UNAUTHORIZED = ("ERR_UNAUTHORIZED", 403, "Caller is not permitted to perform this operation.")
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404, "Requested resource does not exist.")
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409, "Target entity is not in the from-state required for this transition.")
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412, "Expected version does not match current version.")
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400, "Request payload is malformed or missing required fields.")
ERR_INVALID_CONVERSION_PAIR = ("ERR_INVALID_CONVERSION_PAIR", 422, "Conversion source/target type or ownership mismatch.")
ERR_KIND_ACCOUNT_MISMATCH = ("ERR_KIND_ACCOUNT_MISMATCH", 422, "Contribution kind incompatible with account type.")
ERR_TAX_YEAR_CLOSED = ("ERR_TAX_YEAR_CLOSED", 422, "Contribution tax_year does not match the account's tax_year_marker.")
ERR_BENEFICIARY_SHARES_INVALID = ("ERR_BENEFICIARY_SHARES_INVALID", 422, "Active beneficiary share sum must equal 10000.")
ERR_CONTRIBUTION_CAP_EXCEEDED = ("ERR_CONTRIBUTION_CAP_EXCEEDED", 422, "Confirming this contribution would exceed the contribution cap.")
ERR_INSUFFICIENT_BALANCE = ("ERR_INSUFFICIENT_BALANCE", 422, "Distribution amount or withholding exceeds available balance.")
ERR_SECURE_DEADLINE_PASSED = ("ERR_SECURE_DEADLINE_PASSED", 422, "SECURE Act ten-year deadline has been or would be missed.")


def raise_api(catalog_tuple, message: str = ""):
    eid, http, default_msg = catalog_tuple
    raise APIError(eid, http, message or default_msg)
