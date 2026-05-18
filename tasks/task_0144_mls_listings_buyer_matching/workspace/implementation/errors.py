"""Custom error type + canonical constructors mirroring the error catalogue."""
from __future__ import annotations


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- 401 ---
def err_auth_missing(msg="Authentication headers missing."):
    return ApiError("ERR_AUTH_MISSING", 401, msg)


def err_auth_invalid(msg="Authentication headers invalid."):
    return ApiError("ERR_AUTH_INVALID", 401, msg)


# --- 403 ---
def err_forbidden(msg="Role not permitted for this endpoint."):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_forbidden_not_owner(msg="Caller is not the owning agent for this resource."):
    return ApiError("ERR_FORBIDDEN_NOT_OWNER", 403, msg)


# --- 404 ---
def err_not_found(msg="Resource not found."):
    return ApiError("ERR_NOT_FOUND", 404, msg)


# --- 409 ---
def err_invalid_state(msg="Operation not permitted in current state."):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_listing_already_under_contract(msg="Listing is already UNDER_CONTRACT."):
    return ApiError("ERR_LISTING_ALREADY_UNDER_CONTRACT", 409, msg)


def err_offer_not_submitted(msg="Offer is not in SUBMITTED state."):
    return ApiError("ERR_OFFER_NOT_SUBMITTED", 409, msg)


def err_lockbox_state(msg="Lockbox is in the wrong state for this transition."):
    return ApiError("ERR_LOCKBOX_STATE", 409, msg)


def err_lockbox_not_armed(msg="Lockbox must be ARMED for this action."):
    return ApiError("ERR_LOCKBOX_NOT_ARMED", 409, msg)


def err_showing_time_overlap(msg="Showing time overlaps an existing SCHEDULED showing."):
    return ApiError("ERR_SHOWING_TIME_OVERLAP", 409, msg)


def err_counter_expired(msg="Counter has expired."):
    return ApiError("ERR_COUNTER_EXPIRED", 409, msg)


def err_offer_expired(msg="Offer has expired."):
    return ApiError("ERR_OFFER_EXPIRED", 409, msg)


def err_version_conflict(msg="Version mismatch on optimistic concurrency check."):
    return ApiError("ERR_VERSION_CONFLICT", 409, msg)


def err_contingency_already_failed(msg="Contingency is already FAILED."):
    return ApiError("ERR_CONTINGENCY_ALREADY_FAILED", 409, msg)


# --- 422 ---
def err_contingency_deadline_invalid(msg="Contingency deadline_at invalid."):
    return ApiError("ERR_CONTINGENCY_DEADLINE_INVALID", 422, msg)


def err_invalid_listing_fields(msg="Listing fields are invalid."):
    return ApiError("ERR_INVALID_LISTING_FIELDS", 422, msg)


def err_invalid_buyer_fields(msg="Buyer fields are invalid."):
    return ApiError("ERR_INVALID_BUYER_FIELDS", 422, msg)


def err_invalid_offer_fiscal(msg="Offer fiscal fields are invalid."):
    return ApiError("ERR_INVALID_OFFER_FISCAL", 422, msg)


def err_invalid_showing_window(msg="Showing window is invalid."):
    return ApiError("ERR_INVALID_SHOWING_WINDOW", 422, msg)
