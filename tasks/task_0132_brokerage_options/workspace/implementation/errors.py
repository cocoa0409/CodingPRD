"""Custom error type carrying error_id, http_status, and message.

Error IDs and HTTP statuses come directly from SCAFFOLD.yaml errors[] /
PRD §5 error catalogue. The thin wrapper functions below exist so other
modules raise by name rather than by string literal.
"""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ── Auth / RBAC ─────────────────────────────────────────────────────────────
def err_auth_missing(msg="Authentication headers missing or empty."):
    return ApiError("ERR_AUTH_MISSING", 401, msg)


def err_auth_invalid_role(msg="X-User-Role value not recognised."):
    return ApiError("ERR_AUTH_INVALID_ROLE", 401, msg)


def err_forbidden(msg="Role not authorised for this endpoint."):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_ownership(msg="Resource does not chain back to caller's Customer."):
    return ApiError("ERR_OWNERSHIP_VIOLATION", 403, msg)


# ── Existence ───────────────────────────────────────────────────────────────
def err_customer_not_found(msg="Customer not found."):
    return ApiError("ERR_CUSTOMER_NOT_FOUND", 404, msg)


def err_account_not_found(msg="Account not found."):
    return ApiError("ERR_ACCOUNT_NOT_FOUND", 404, msg)


def err_options_approval_not_found(msg="OptionsApproval not found."):
    return ApiError("ERR_OPTIONS_APPROVAL_NOT_FOUND", 404, msg)


def err_order_not_found(msg="Order not found."):
    return ApiError("ERR_ORDER_NOT_FOUND", 404, msg)


def err_transfer_not_found(msg="ACATTransfer not found."):
    return ApiError("ERR_TRANSFER_NOT_FOUND", 404, msg)


# ── Generic / state ─────────────────────────────────────────────────────────
def err_validation(msg="Request validation failed."):
    return ApiError("ERR_VALIDATION", 422, msg)


def err_invalid_state(msg="Resource not in valid source state."):
    return ApiError("ERR_INVALID_STATE", 409, msg)


# ── Posture gates ───────────────────────────────────────────────────────────
def err_account_not_approved(msg="Account is not APPROVED."):
    return ApiError("ERR_ACCOUNT_NOT_APPROVED", 409, msg)


def err_kyc_not_verified(msg="Customer KYC is not VERIFIED."):
    return ApiError("ERR_KYC_NOT_VERIFIED", 409, msg)


def err_trading_frozen(msg="Account trading posture is not OPEN."):
    return ApiError("ERR_TRADING_FROZEN", 409, msg)


# ── KYC ─────────────────────────────────────────────────────────────────────
def err_kyc_ineligible_country(msg="KYC address_country must be 'US'."):
    return ApiError("ERR_KYC_INELIGIBLE_COUNTRY", 422, msg)


def err_kyc_age_ineligible(msg="Customer must be at least 18 years old."):
    return ApiError("ERR_KYC_AGE_INELIGIBLE", 422, msg)


def err_w9_name_mismatch(msg="W-9 signed name does not match Customer.legal_name."):
    return ApiError("ERR_W9_NAME_MISMATCH", 422, msg)


# ── Options ─────────────────────────────────────────────────────────────────
def err_options_level_insufficient(msg="Account options_level is below the strategy minimum."):
    return ApiError("ERR_OPTIONS_LEVEL_INSUFFICIENT", 422, msg)


def err_options_level_exceeds_eligibility(msg="approved_level exceeds the eligibility cap."):
    return ApiError("ERR_OPTIONS_LEVEL_EXCEEDS_ELIGIBILITY", 422, msg)


def err_options_approval_in_progress(msg="A non-terminal OptionsApproval already exists for this account."):
    return ApiError("ERR_OPTIONS_APPROVAL_IN_PROGRESS", 409, msg)


def err_revision_limit_reached(msg="revision_count has reached its limit."):
    return ApiError("ERR_REVISION_LIMIT_REACHED", 409, msg)


# ── Orders / margin / PDT ──────────────────────────────────────────────────
def err_order_price_missing(msg="Required price field missing for this order_type."):
    return ApiError("ERR_ORDER_PRICE_MISSING", 422, msg)


def err_order_strategy_required(msg="option_strategy required iff instrument_type=OPTION."):
    return ApiError("ERR_ORDER_STRATEGY_REQUIRED", 422, msg)


def err_fill_price_violates_limits(msg="Execution price violates LIMIT/STOP semantics."):
    return ApiError("ERR_FILL_PRICE_VIOLATES_LIMITS", 422, msg)


def err_pdt_equity_below_minimum(msg="PDT-flagged account equity is below $25,000."):
    return ApiError("ERR_PDT_EQUITY_BELOW_MINIMUM", 409, msg)


def err_insufficient_margin(msg="Computed margin requirement exceeds cash_balance_cents."):
    return ApiError("ERR_INSUFFICIENT_MARGIN", 422, msg)


# ── ACAT / Account close ────────────────────────────────────────────────────
def err_open_orders_block_transfer(msg="Outbound ACAT validate blocked by open Orders."):
    return ApiError("ERR_OPEN_ORDERS_BLOCK_TRANSFER", 409, msg)


def err_account_has_dependencies(msg="Account has unsettled dependencies."):
    return ApiError("ERR_ACCOUNT_HAS_DEPENDENCIES", 409, msg)


def err_transfer_already_pending(msg="Another OUTBOUND ACATTransfer is already pending for this account."):
    return ApiError("ERR_TRANSFER_ALREADY_PENDING", 409, msg)
