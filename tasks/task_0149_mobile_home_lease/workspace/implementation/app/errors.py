"""Error catalog and exception types for the Mobile Home Lease API."""
from __future__ import annotations

from typing import Any, Optional

from flask import Flask


# Error catalog: error_id -> (default_message, http_status)
ERROR_CATALOG: dict[str, tuple[str, int]] = {
    "ERR_AUTH_REQUIRED": ("Authentication headers missing or empty.", 401),
    "ERR_FORBIDDEN": ("Role is not authorized for this operation.", 403),
    "ERR_FORBIDDEN_NOT_OWNER": ("Acting principal does not own this resource.", 403),
    "ERR_RESOURCE_NOT_FOUND": ("Referenced resource does not exist.", 404),
    "ERR_REFERENCED_RESOURCE_NOT_FOUND": ("Resource referenced in body does not exist.", 404),
    "ERR_INVALID_STATE": ("Target resource is not in a valid state for this transition.", 409),
    "ERR_VERSION_MISMATCH": ("Optimistic concurrency version mismatch.", 409),
    "ERR_VALIDATION": ("Request body validation failed.", 422),
    "ERR_NO_CURE_PERMITTED": ("Cure is not permitted for ILLEGAL_USE violations.", 409),
    "ERR_BUYER_INELIGIBLE": ("Buyer has a disqualifying eviction history.", 422),
    "ERR_LOT_OCCUPIED": ("Lot already has an active lease.", 409),
    "ERR_LOT_ALREADY_RESIDENT_OWNED": ("Lot is already resident-owned.", 409),
    "ERR_HOME_NOT_RESIDENT_OWNED": ("Home is not resident-owned and cannot be sold.", 409),
    "ERR_NOTICE_WINDOW_TOO_SHORT": ("Rent-increase notice must be issued at least 90 days before effective date.", 422),
    "ERR_CURE_WINDOW_EXPIRED": ("Cure deadline has passed.", 409),
    "ERR_RENT_INCREASE_BLOCKED_DURING_EVICTION": ("Rent-increase issuance blocked while lease is in GRACE.", 409),
    "ERR_RENT_INCREASE_NONPOSITIVE": ("Proposed new rent must be strictly greater than current rent.", 422),
    "ERR_BALANCE_NOT_ZERO": ("Outstanding balance must be zero to cure a NONPAYMENT case.", 409),
    "ERR_BUYOUT_UNDERVALUED": ("Conversion offer price is below the home's assessed value.", 422),
    "ERR_LOT_OCCUPIED_BY_PENDING_OP": ("Lot is occupied by a pending concurrent operation.", 409),
    "ERR_DUPLICATE_VIN": ("Home VIN already exists.", 409),
    "ERR_DUPLICATE_LOT_NUMBER": ("Lot number already exists within this park.", 409),
}


class ApiError(Exception):
    """Application-level error carrying an error_id, message and HTTP status."""

    def __init__(self, error_id: str, message: Optional[str] = None, http_status: Optional[int] = None) -> None:
        default_msg, default_status = ERROR_CATALOG.get(error_id, ("Unknown error.", 500))
        self.error_id = error_id
        self.message = message if message is not None else default_msg
        self.http_status = http_status if http_status is not None else default_status
        super().__init__(self.message)


def register_error_handlers(app: Flask) -> None:
    from .responses import error_response

    @app.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError):  # type: ignore[unused-variable]
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc: Exception):  # type: ignore[unused-variable]
        # Defensive: surface unknown errors as ERR_VALIDATION/500 isn't in catalog;
        # use a generic envelope.
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_VALIDATION", f"Unexpected error: {exc}", 500)


__all__ = ["ApiError", "ERROR_CATALOG", "register_error_handlers"]
