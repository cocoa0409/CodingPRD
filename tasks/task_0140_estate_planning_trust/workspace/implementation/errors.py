"""Custom error type and a single registry of (error_id, http_status) pairs
drawn verbatim from SCAFFOLD §1.6 / PRD §5.
"""
from __future__ import annotations


class ApiError(Exception):
    """Raised by any layer to signal an API-level failure with an error_id."""

    def __init__(self, error_id: str, http_status: int, message: str | None = None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Registry of canonical error_id → http_status from PRD §5.
ERROR_HTTP_STATUS: dict[str, int] = {
    "ERR_BAD_REQUEST": 400,
    "ERR_AUTH_REQUIRED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_HIPAA_SCOPE_INSUFFICIENT": 403,
    "ERR_POA_SCOPE_INSUFFICIENT": 403,
    "ERR_FILING_NOT_PERMITTED": 403,
    "ERR_POSTURE_BLOCKED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_VERSION_MISMATCH": 409,
    "ERR_FILING_ALREADY_PENDING": 409,
    "ERR_DUPLICATE_EXECUTOR": 409,
    "ERR_NO_SUCCESSOR": 409,
    "ERR_NO_CONFIRMED_EXECUTOR": 409,
    "ERR_NO_ACCEPTED_PETITION": 409,
    "ERR_NO_ACCEPTED_INVENTORY": 409,
    "ERR_NO_ACCEPTED_DISTRIBUTION_PETITION": 409,
    "ERR_NO_ACCEPTED_FINAL_ACCOUNTING": 409,
    "ERR_ASSETS_NOT_INVENTORIED": 409,
    "ERR_ASSETS_NOT_DISTRIBUTED": 409,
    "ERR_ASSET_ALREADY_DISTRIBUTED": 409,
    "ERR_HAS_DEPENDENCIES": 409,
    "ERR_DESIGNATION_MISMATCH": 409,
    "ERR_FILINGS_PENDING": 409,
    "ERR_DISTRIBUTIONS_PENDING": 409,
    "ERR_DESIGNATION_OVER_ALLOCATED": 422,
    "ERR_DESIGNATIONS_INCOMPLETE": 422,
    "ERR_GUARDIANSHIP_MISSING": 422,
    "ERR_NO_MINOR_BENEFICIARY": 422,
    "ERR_BOND_INSUFFICIENT": 422,
    "ERR_DISTRIBUTION_DRIFT": 422,
    "ERR_DIRECTIVE_EFFECTIVE_PAST": 422,
    "ERR_SETTLEMENT_DEADLINE_PASSED": 422,
}


def raise_err(error_id: str, message: str | None = None):
    """Look up the canonical HTTP status for `error_id` and raise."""
    status = ERROR_HTTP_STATUS.get(error_id)
    if status is None:
        # Unknown error_id — surface as a server error rather than silently
        # mapping to 500.
        raise ApiError("ERR_BAD_REQUEST", 400, message or error_id)
    raise ApiError(error_id, status, message)
