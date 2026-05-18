"""Custom ApiError type carrying error_id / http_status / message.

The error_id values come from SCAFFOLD §1.6 (also catalogued in PRD §5).
"""
from __future__ import annotations


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ── Auth (400 / 403) ────────────────────────────────────────────────────────

def err_missing_or_invalid_user_context(msg="X-User-ID or X-User-Role header missing or malformed."):
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400, msg)


def err_forbidden_role(msg="Role is not permitted for this operation."):
    return ApiError("ERR_FORBIDDEN_ROLE", 403, msg)


# ── Existence (404) ─────────────────────────────────────────────────────────

def err_customer_not_found(msg="Customer not found."):
    return ApiError("ERR_CUSTOMER_NOT_FOUND", 404, msg)


def err_contract_not_found(msg="Contract not found."):
    return ApiError("ERR_CONTRACT_NOT_FOUND", 404, msg)


def err_vehicle_not_found(msg="Vehicle not found."):
    return ApiError("ERR_VEHICLE_NOT_FOUND", 404, msg)


def err_payment_not_found(msg="Payment not found."):
    return ApiError("ERR_PAYMENT_NOT_FOUND", 404, msg)


def err_assessment_not_found(msg="Lease-end assessment not found."):
    return ApiError("ERR_ASSESSMENT_NOT_FOUND", 404, msg)


def err_rider_not_found(msg="Gap rider not found."):
    return ApiError("ERR_RIDER_NOT_FOUND", 404, msg)


# ── State (409) ─────────────────────────────────────────────────────────────

def err_customer_not_active(msg="Customer is not ACTIVE."):
    return ApiError("ERR_CUSTOMER_NOT_ACTIVE", 409, msg)


def err_loan_not_pending_approval(msg="Loan is not in PENDING_APPROVAL."):
    return ApiError("ERR_LOAN_NOT_PENDING_APPROVAL", 409, msg)


def err_lease_not_pending_approval(msg="Lease is not in PENDING_APPROVAL."):
    return ApiError("ERR_LEASE_NOT_PENDING_APPROVAL", 409, msg)


def err_contract_not_activatable(msg="Contract requires APPROVED status to activate."):
    return ApiError("ERR_CONTRACT_NOT_ACTIVATABLE", 409, msg)


def err_loan_not_defaulted(msg="Loan is not DEFAULTED."):
    return ApiError("ERR_LOAN_NOT_DEFAULTED", 409, msg)


def err_lease_not_matured(msg="Lease is not MATURED."):
    return ApiError("ERR_LEASE_NOT_MATURED", 409, msg)


def err_payment_not_payable(msg="Payment is not payable in its current state."):
    return ApiError("ERR_PAYMENT_NOT_PAYABLE", 409, msg)


def err_assessment_not_issued(msg="Assessment is not in ISSUED state."):
    return ApiError("ERR_ASSESSMENT_NOT_ISSUED", 409, msg)


def err_assessment_not_disputed(msg="Assessment is not in DISPUTED state."):
    return ApiError("ERR_ASSESSMENT_NOT_DISPUTED", 409, msg)


def err_gap_rider_not_claimable(msg="Gap rider is not in ACTIVE state."):
    return ApiError("ERR_GAP_RIDER_NOT_CLAIMABLE", 409, msg)


def err_gap_rider_parent_terminal(msg="Parent contract is in a terminal state; claim is not allowed."):
    return ApiError("ERR_GAP_RIDER_PARENT_TERMINAL", 409, msg)


def err_payment_due_date_collision(msg="A payment already occupies this due_day_index."):
    return ApiError("ERR_PAYMENT_DUE_DATE_COLLISION", 409, msg)


def err_lease_window_overlap(msg="Lease term window overlaps with another non-terminal lease."):
    return ApiError("ERR_LEASE_WINDOW_OVERLAP", 409, msg)


def err_version_conflict(msg="Optimistic concurrency: version mismatch."):
    return ApiError("ERR_VERSION_CONFLICT", 409, msg)


def err_reinstate_has_outstanding_defaults(msg="Loan still has DEFAULTED payments outstanding."):
    return ApiError("ERR_REINSTATE_HAS_OUTSTANDING_DEFAULTS", 409, msg)


# ── Validation (400 / 422) ──────────────────────────────────────────────────

def err_invalid_request(msg="Invalid request."):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_fico_out_of_range(msg="fico_score must be in [300, 850]."):
    return ApiError("ERR_FICO_OUT_OF_RANGE", 422, msg)


def err_vehicle_not_available(msg="Vehicle is not AVAILABLE."):
    return ApiError("ERR_VEHICLE_NOT_AVAILABLE", 422, msg)


def err_down_payment_below_minimum(msg="down_payment_cents below the FICO-tier minimum."):
    return ApiError("ERR_DOWN_PAYMENT_BELOW_MINIMUM", 422, msg)


def err_lease_tier_ineligible(msg="Lease is not available for this FICO tier."):
    return ApiError("ERR_LEASE_TIER_INELIGIBLE", 422, msg)


def err_loan_tier_declined(msg="Loan is not available for TIER_5_DECLINED."):
    return ApiError("ERR_LOAN_TIER_DECLINED", 422, msg)


def err_rider_contract_ownership_mismatch(msg="Referenced contract is not owned by this customer."):
    return ApiError("ERR_RIDER_CONTRACT_OWNERSHIP_MISMATCH", 422, msg)


def err_gap_claim_exceeds_gap(msg="Claim payout exceeds the contract gap."):
    return ApiError("ERR_GAP_CLAIM_EXCEEDS_GAP", 422, msg)


def err_invalid_odometer_reading(msg="odometer_reading must be a non-negative integer."):
    return ApiError("ERR_INVALID_ODOMETER_READING", 422, msg)


def err_invalid_lease_end_election(msg="election must be PURCHASE, RENEW, or RETURN."):
    return ApiError("ERR_INVALID_LEASE_END_ELECTION", 422, msg)


def err_clock_advance_out_of_range(msg="days_advanced must be in [1, 365]."):
    return ApiError("ERR_CLOCK_ADVANCE_OUT_OF_RANGE", 422, msg)
