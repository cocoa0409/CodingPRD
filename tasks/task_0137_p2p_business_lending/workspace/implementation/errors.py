"""Custom error type carrying error_id, message and HTTP status — see SCAFFOLD §1.6."""
from __future__ import annotations


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ── Auth / existence ────────────────────────────────────────────────────────


def err_missing_user_context(msg="X-User-Role and X-User-ID headers are required."):
    return ApiError("ERR_MISSING_USER_CONTEXT", 400, msg)


def err_forbidden_for_role(msg="Role is not permitted for this endpoint."):
    return ApiError("ERR_FORBIDDEN_FOR_ROLE", 403, msg)


def err_not_found(msg="Resource not found."):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_request(msg="Malformed or invalid request."):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


# ── State ──────────────────────────────────────────────────────────────────


def err_invalid_state_transition(msg="Operation not legal in current state."):
    return ApiError("ERR_INVALID_STATE_TRANSITION", 409, msg)


# ── Segregation of duties ─────────────────────────────────────────────────


def err_segregation_violation(msg="Action prohibited by segregation of duties."):
    return ApiError("ERR_SEGREGATION_VIOLATION", 403, msg)


# ── Borrower ──────────────────────────────────────────────────────────────


def err_duplicate_ein(msg="Another borrower on this platform already uses this EIN."):
    return ApiError("ERR_DUPLICATE_EIN", 409, msg)


def err_no_plaid_snapshot(msg="Borrower has no PlaidSnapshot."):
    return ApiError("ERR_NO_PLAID_SNAPSHOT", 409, msg)


def err_borrower_ungraded(msg="Borrower final_grade is UNGRADED."):
    return ApiError("ERR_BORROWER_UNGRADED", 409, msg)


def err_borrower_not_approved(msg="Operation requires borrower in APPROVED status."):
    return ApiError("ERR_BORROWER_NOT_APPROVED", 409, msg)


def err_borrower_not_listable(msg="Borrower not listable: already has OPEN/FUNDED listing or not APPROVED."):
    return ApiError("ERR_BORROWER_NOT_LISTABLE", 409, msg)


def err_borrower_has_losses(msg="Borrower has a Loan in CHARGED_OFF; reinstate forbidden."):
    return ApiError("ERR_BORROWER_HAS_LOSSES", 409, msg)


# ── Listing / Investment ───────────────────────────────────────────────────


def err_listing_oversubscribed(msg="Investment would push pledged_cents above principal_cents."):
    return ApiError("ERR_LISTING_OVERSUBSCRIBED", 409, msg)


def err_listing_integrity(msg="One or more investments are not COMMITTED."):
    return ApiError("ERR_LISTING_INTEGRITY", 409, msg)


def err_diversification_cap_exceeded(msg="Borrower exposure would exceed concentration cap."):
    return ApiError("ERR_DIVERSIFICATION_CAP_EXCEEDED", 409, msg)


def err_cross_platform_investment(msg="Investor and listing belong to different platforms."):
    return ApiError("ERR_CROSS_PLATFORM_INVESTMENT", 409, msg)


def err_insufficient_cash(msg="Investor cash balance below requested investment amount."):
    return ApiError("ERR_INSUFFICIENT_CASH", 409, msg)


def err_investment_denomination(msg="Investment amount must be >= 2500 cents and a multiple of 100."):
    return ApiError("ERR_INVESTMENT_DENOMINATION", 422, msg)


# ── Loan / Payment ────────────────────────────────────────────────────────


def err_loan_not_payable(msg="Loan is not in a payable state."):
    return ApiError("ERR_LOAN_NOT_PAYABLE", 409, msg)


# ── Disclosure ────────────────────────────────────────────────────────────


def err_disclosure_locked(msg="Disclosure is PUBLISHED and immutable."):
    return ApiError("ERR_DISCLOSURE_LOCKED", 409, msg)


def err_disclosure_stale(msg="Disclosure subject has changed state since DRAFT."):
    return ApiError("ERR_DISCLOSURE_STALE", 409, msg)
