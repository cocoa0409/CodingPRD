"""Custom error type for the Personal Injury Case API.

Every error_id and HTTP status comes from SCAFFOLD §1.6 / PRD §5.
Do not invent new codes — only the catalog values are valid.
"""
from __future__ import annotations


class ApiError(Exception):
    """Raised by any layer to signal an API-level failure with an error_id."""

    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Catalog (id → http_status) — single source of truth.
ERROR_CATALOG = {
    # Auth / RBAC
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # Existence
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    # State / lifecycle
    "ERR_INVALID_STATE": 409,
    "ERR_CASE_CLOSED": 409,
    "ERR_CASE_INVALID_STATE": 409,
    "ERR_DEMAND_NOT_DRAFT": 409,
    "ERR_OFFER_NOT_PENDING": 409,
    "ERR_DAMAGES_ALREADY_EXISTS": 409,
    "ERR_FEE_AGREEMENT_ALREADY_EXISTS": 409,
    "ERR_ACTIVE_DEMAND_EXISTS": 409,
    "ERR_STALE_DAMAGES_SNAPSHOT": 409,
    "ERR_DISBURSEMENT_ALREADY_APPROVED": 409,
    "ERR_VERSION_MISMATCH": 409,
    "ERR_ATTORNEY_CALENDAR_CONFLICT": 409,
    "ERR_COURTROOM_DOUBLE_BOOKED": 409,
    # Business / temporal / fiscal
    "ERR_STATUTE_OF_LIMITATIONS_EXPIRED": 422,
    "ERR_DATE_OF_SERVICE_INVALID": 422,
    "ERR_OFFER_PARTY_INVALID": 422,
    "ERR_LIEN_NEGOTIATION_INVALID": 422,
    "ERR_DEMAND_BELOW_DAMAGES": 422,
    "ERR_DAMAGES_METHOD_INPUTS_INVALID": 422,
    "ERR_COURT_EVENT_TIME_INVALID": 422,
    "ERR_NET_BELOW_ZERO": 422,
    "ERR_COSTS_DECREASE_NOT_ALLOWED": 422,
    # Generic input validation (not in catalog but used for HTTP-level shape
    # errors only; never returned as a primary business error_id).
    "ERR_VALIDATION": 422,
}


def raise_error(error_id: str, message: str = "") -> None:
    """Raise an ApiError using the catalog-defined HTTP status."""
    status = ERROR_CATALOG.get(error_id)
    if status is None:
        raise ApiError("ERR_VALIDATION", 422, message or error_id)
    raise ApiError(error_id, status, message or error_id)
