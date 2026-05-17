"""Custom error type carrying error_id, message and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Quick constructors that mirror the error catalogue.
def err_auth_missing(msg="Authentication headers missing or invalid."):
    return ApiError("ERR_AUTH_MISSING", 401, msg)


def err_forbidden(msg="Acting role is not permitted for this endpoint."):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_segregation(msg="Segregation of duties violated."):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


def err_loan_not_found(msg="Loan not found."):
    return ApiError("ERR_LOAN_NOT_FOUND", 404, msg)


def err_resource_not_found(msg="Resource not found."):
    return ApiError("ERR_RESOURCE_NOT_FOUND", 404, msg)


def err_invalid_state(msg="Operation not permitted in current state."):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_concurrent_update(msg="Version mismatch on optimistic concurrency check."):
    return ApiError("ERR_CONCURRENT_UPDATE", 409, msg)


def err_escrow_analysis_conflict(msg="Another EscrowAnalysis was finalized concurrently."):
    return ApiError("ERR_ESCROW_ANALYSIS_CONFLICT", 409, msg)


def err_forbearance_plan_exists(msg="Loan already has an active ForbearancePlan."):
    return ApiError("ERR_FORBEARANCE_PLAN_EXISTS", 409, msg)


def err_foreclosure_case_exists(msg="Loan already has an open ForeclosureCase."):
    return ApiError("ERR_FORECLOSURE_CASE_EXISTS", 409, msg)


def err_mediation_already_open(msg="ForeclosureCase already has an active MediationCase."):
    return ApiError("ERR_MEDIATION_ALREADY_OPEN", 409, msg)


def err_noi_window_not_elapsed(msg="NOI window has not elapsed."):
    return ApiError("ERR_NOI_WINDOW_NOT_ELAPSED", 422, msg)


def err_auction_notice(msg="Auction notice rule violated."):
    return ApiError("ERR_AUCTION_NOTICE_VIOLATION", 422, msg)


def err_mediation_window_closed(msg="Mediation requested after NOI window expired."):
    return ApiError("ERR_MEDIATION_WINDOW_CLOSED", 422, msg)


def err_hardship_missing(msg="Borrower hardship affidavit is required."):
    return ApiError("ERR_HARDSHIP_AFFIDAVIT_MISSING", 422, msg)


def err_reinstatement_cutoff(msg="Reinstatement attempted within the 5-day auction cutoff."):
    return ApiError("ERR_REINSTATEMENT_CUTOFF", 422, msg)


def err_pmi_ltv(msg="evaluated_ltv_bps exceeds the threshold for this trigger."):
    return ApiError("ERR_PMI_LTV_TOO_HIGH", 422, msg)


def err_pmi_history(msg="Payment history is insufficient for PMI removal."):
    return ApiError("ERR_PMI_HISTORY_INSUFFICIENT", 422, msg)


def err_hamp_not_a_reduction(msg="HAMP offer does not reduce the scheduled payment."):
    return ApiError("ERR_HAMP_NOT_A_REDUCTION", 422, msg)


def err_hamp_floor(msg="HAMP offer falls below the affordability floor."):
    return ApiError("ERR_HAMP_AFFORDABILITY_FLOOR", 422, msg)


def err_hamp_stale(msg="HAMP offer has gone stale; recompute exceeds 100 cents tolerance."):
    return ApiError("ERR_HAMP_STALE_OFFER", 422, msg)


def err_escrow_baseline(msg="starting_balance_cents does not match current escrow balance or analysis_date is too early."):
    return ApiError("ERR_ESCROW_BASELINE_MISMATCH", 422, msg)


def err_payment_amount(msg="Payment amount must be strictly positive."):
    return ApiError("ERR_PAYMENT_AMOUNT_INVALID", 422, msg)


def err_reinstatement_insufficient(msg="Reinstatement payment is less than the quoted amount."):
    return ApiError("ERR_REINSTATEMENT_INSUFFICIENT", 422, msg)


def err_insufficient_escrow(msg="Escrow balance is insufficient for this disbursement."):
    return ApiError("ERR_INSUFFICIENT_ESCROW", 422, msg)


def err_forbearance_date(msg="ForbearancePlan.start_date must be on or before Loan.next_due_date."):
    return ApiError("ERR_FORBEARANCE_DATE_INVALID", 422, msg)
