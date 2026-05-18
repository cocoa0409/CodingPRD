"""Error catalog for the Trust Accounting API (scaffold §1.6)."""
from __future__ import annotations


class ApiError(Exception):
    """Custom exception carrying error_id, http_status, and human message."""

    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ── Short helper constructors mirroring the scaffold error catalog ──────────


def err_unauthenticated(msg: str = "Missing or invalid auth headers.") -> ApiError:
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg: str = "Role not permitted for this endpoint.") -> ApiError:
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_not_found(msg: str = "Resource not found.") -> ApiError:
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_version_mismatch(msg: str = "Stale resource version.") -> ApiError:
    return ApiError("ERR_VERSION_MISMATCH", 409, msg)


def err_invalid_state(msg: str = "Operation not permitted in current state.") -> ApiError:
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_beneficiary_terminated(msg: str = "Beneficiary is terminated.") -> ApiError:
    return ApiError("ERR_BENEFICIARY_TERMINATED", 409, msg)


def err_segregation(msg: str = "Segregation of duties violated.") -> ApiError:
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


def err_irrevocable_cannot_revoke(msg: str = "Irrevocable trust cannot be revoked or mutated.") -> ApiError:
    return ApiError("ERR_IRREVOCABLE_CANNOT_REVOKE", 403, msg)


def err_tax_year_closed(msg: str = "Tax year is not OPEN/CLOSING.") -> ApiError:
    return ApiError("ERR_TAX_YEAR_CLOSED", 409, msg)


def err_tax_year_not_open(msg: str = "Tax year is not OPEN.") -> ApiError:
    return ApiError("ERR_TAX_YEAR_NOT_OPEN", 409, msg)


def err_tax_year_not_ended(msg: str = "Tax year has not ended.") -> ApiError:
    return ApiError("ERR_TAX_YEAR_NOT_ENDED", 409, msg)


def err_tax_year_closing_in_progress(msg: str = "Tax year is currently closing.") -> ApiError:
    return ApiError("ERR_TAX_YEAR_CLOSING_IN_PROGRESS", 409, msg)


def err_tax_year_not_closed(msg: str = "Current tax year is not closed.") -> ApiError:
    return ApiError("ERR_TAX_YEAR_NOT_CLOSED", 409, msg)


def err_newer_year_closed(msg: str = "A later tax year has already been closed.") -> ApiError:
    return ApiError("ERR_NEWER_YEAR_CLOSED", 409, msg)


def err_no_primary_trustee(msg: str = "Exactly one ACTIVE primary trustee required.") -> ApiError:
    return ApiError("ERR_NO_PRIMARY_TRUSTEE", 409, msg)


def err_no_beneficiary(msg: str = "At least one ACTIVE beneficiary required.") -> ApiError:
    return ApiError("ERR_NO_BENEFICIARY", 409, msg)


def err_no_open_tax_year(msg: str = "An open tax year for inception_date is required.") -> ApiError:
    return ApiError("ERR_NO_OPEN_TAX_YEAR", 409, msg)


def err_grantor_status_incompatible(
    msg: str = "GRANTOR tax status incompatible with IRREVOCABLE trust without grantor powers.",
) -> ApiError:
    return ApiError("ERR_GRANTOR_STATUS_INCOMPATIBLE", 422, msg)


def err_insufficient_principal(msg: str = "Distribution exceeds available principal_balance.") -> ApiError:
    return ApiError("ERR_INSUFFICIENT_PRINCIPAL", 409, msg)


def err_insufficient_income(msg: str = "Distribution exceeds available income_balance.") -> ApiError:
    return ApiError("ERR_INSUFFICIENT_INCOME", 409, msg)


def err_insufficient_income_for_tax(
    msg: str = "income_balance insufficient to pay computed trust_income_tax.",
) -> ApiError:
    return ApiError("ERR_INSUFFICIENT_INCOME_FOR_TAX", 409, msg)


def err_has_approved_distributions(msg: str = "Pending APPROVED distributions block this operation.") -> ApiError:
    return ApiError("ERR_HAS_APPROVED_DISTRIBUTIONS", 409, msg)


def err_has_pending_distributions(msg: str = "Pending distributions reference this beneficiary.") -> ApiError:
    return ApiError("ERR_HAS_PENDING_DISTRIBUTIONS", 409, msg)


def err_has_undistributed_assets(msg: str = "Funded assets remain.") -> ApiError:
    return ApiError("ERR_HAS_UNDISTRIBUTED_ASSETS", 409, msg)


def err_nonzero_balance(msg: str = "Trust balances are not zero.") -> ApiError:
    return ApiError("ERR_NONZERO_BALANCE", 409, msg)


def err_trust_not_active(msg: str = "Trust is not ACTIVE.") -> ApiError:
    return ApiError("ERR_TRUST_NOT_ACTIVE", 409, msg)


def err_k1_stale_reference(msg: str = "K-1 underlying distribution versions drifted since amendment.") -> ApiError:
    return ApiError("ERR_K1_STALE_REFERENCE", 409, msg)


def err_bad_request(msg: str = "Malformed request body.") -> ApiError:
    return ApiError("ERR_BAD_REQUEST", 400, msg)
