"""Custom error class carrying error_id, message, and HTTP status."""
from __future__ import annotations


class APIError(Exception):
    """Application-level error carrying error_id, human-readable message, and HTTP status."""

    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# ----- Error code constants (HTTP status comes from the scaffold's error catalog) -----
ERR_AUTH_REQUIRED = ("ERR_AUTH_REQUIRED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_LIABILITY_NOT_OWNED = ("ERR_LIABILITY_NOT_OWNED", 404)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_LIABILITY_NOT_ELIGIBLE = ("ERR_LIABILITY_NOT_ELIGIBLE", 409)
ERR_CNC_NOT_ELIGIBLE = ("ERR_CNC_NOT_ELIGIBLE", 422)
ERR_LIABILITY_LOCKED = ("ERR_LIABILITY_LOCKED", 409)
ERR_OVERLAPPING_TOLLING = ("ERR_OVERLAPPING_TOLLING", 409)
ERR_DDIA_REQUIRED = ("ERR_DDIA_REQUIRED", 422)
ERR_INELIGIBLE_AGREEMENT_TYPE = ("ERR_INELIGIBLE_AGREEMENT_TYPE", 422)
ERR_DEPOSIT_INSUFFICIENT = ("ERR_DEPOSIT_INSUFFICIENT", 422)
ERR_OIC_BELOW_RCP = ("ERR_OIC_BELOW_RCP", 422)
ERR_LIEN_WITHDRAWAL_NOT_ELIGIBLE = ("ERR_LIEN_WITHDRAWAL_NOT_ELIGIBLE", 422)
ERR_OVERPAYMENT = ("ERR_OVERPAYMENT", 422)
ERR_CSED_EXPIRED = ("ERR_CSED_EXPIRED", 422)
ERR_SEGREGATION_OF_DUTIES = ("ERR_SEGREGATION_OF_DUTIES", 422)
ERR_VERSION_CONFLICT = ("ERR_VERSION_CONFLICT", 409)
ERR_VALIDATION = ("ERR_VALIDATION", 400)


def raise_error(code_tuple, message: str):
    """Helper to raise an APIError from a (error_id, http_status) tuple."""
    error_id, http_status = code_tuple
    raise APIError(error_id, message, http_status)
