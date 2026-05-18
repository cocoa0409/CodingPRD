"""Custom error type carrying error_id, message and HTTP status — see SCAFFOLD §1.6."""
from __future__ import annotations


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth / RBAC.

def err_auth_missing(msg="Authentication headers missing or malformed."):
    return ApiError("ERR_AUTH_MISSING", 401, msg)


def err_auth_forbidden(msg="Role is not permitted for this operation."):
    return ApiError("ERR_AUTH_FORBIDDEN", 403, msg)


def err_auth_identity_unknown(msg="X-User-ID does not resolve to a backing entity."):
    return ApiError("ERR_AUTH_IDENTITY_UNKNOWN", 403, msg)


# Existence.

def err_resource_not_found(msg="Resource not found."):
    return ApiError("ERR_RESOURCE_NOT_FOUND", 404, msg)


def err_fk_not_found(msg="Foreign-key reference not found."):
    return ApiError("ERR_FK_NOT_FOUND", 422, msg)


# State transitions.

def err_invalid_state(msg="Operation not legal in current state."):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_invalid_trade_state(msg="Trade is not cancellable in current state."):
    return ApiError("ERR_INVALID_TRADE_STATE", 409, msg)


# Business / safety.

def err_account_frozen(msg="Account is frozen for compliance review."):
    return ApiError("ERR_ACCOUNT_FROZEN", 409, msg)


def err_wash_sale(msg="Buy would violate IRS Wash Sale rule."):
    return ApiError("ERR_WASH_SALE_VIOLATION", 422, msg)


def err_security_not_investable(msg="Security is not investable."):
    return ApiError("ERR_SECURITY_NOT_INVESTABLE", 422, msg)


def err_insufficient_lot_shares(msg="Specified lot does not have enough shares remaining."):
    return ApiError("ERR_INSUFFICIENT_LOT_SHARES", 422, msg)


def err_insufficient_position_shares(msg="Position does not have enough shares to sell."):
    return ApiError("ERR_INSUFFICIENT_POSITION_SHARES", 422, msg)


def err_rebalance_already_in_progress(msg="Rebalance already exists for this account/quarter."):
    return ApiError("ERR_REBALANCE_ALREADY_IN_PROGRESS", 409, msg)


def err_drift_below_threshold(msg="Account drift is below the rebalance trigger threshold."):
    return ApiError("ERR_DRIFT_BELOW_THRESHOLD", 422, msg)


def err_harvest_threshold_not_met(msg="No position meets the harvest loss threshold."):
    return ApiError("ERR_HARVEST_THRESHOLD_NOT_MET", 422, msg)


def err_allocation_invalid(msg="Target allocation invalid."):
    return ApiError("ERR_ALLOCATION_INVALID", 422, msg)


def err_correlation_invalid(msg="Correlation value or pair invalid."):
    return ApiError("ERR_CORRELATION_INVALID", 422, msg)


def err_questionnaire_out_of_range(msg="Questionnaire answers must be in [1,5]."):
    return ApiError("ERR_QUESTIONNAIRE_OUT_OF_RANGE", 422, msg)


def err_time_horizon_out_of_range(msg="time_horizon_years must be in [1,40]."):
    return ApiError("ERR_TIME_HORIZON_OUT_OF_RANGE", 422, msg)


def err_form_already_exists(msg="A 1099-B form already exists for this client and tax year."):
    return ApiError("ERR_FORM_ALREADY_EXISTS", 409, msg)


def err_open_trades_for_tax_year(msg="Cannot issue: open SELL trades remain in the tax year."):
    return ApiError("ERR_OPEN_TRADES_FOR_TAX_YEAR", 409, msg)


def err_insufficient_cash(msg="Insufficient cash for this buy."):
    return ApiError("ERR_INSUFFICIENT_CASH", 422, msg)


def err_version_conflict(msg="Optimistic concurrency: version mismatch."):
    return ApiError("ERR_VERSION_CONFLICT", 409, msg)


def err_pagination_invalid(msg="limit must be in [1,100] and offset >= 0."):
    return ApiError("ERR_PAGINATION_INVALID", 422, msg)


def err_client_not_accepting_input(msg="Client is not accepting input in its current state."):
    return ApiError("ERR_CLIENT_NOT_ACCEPTING_INPUT", 409, msg)
