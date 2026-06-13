"""Domain error class and the complete error catalog (PRD §5 / scaffold §1.6).

Each error carries its exact error_id and HTTP status verbatim from the PRD.
"""
from __future__ import annotations


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalog: id -> http status (PRD §5) -------------------------------
ERROR_CATALOG = {
    "ERR_MISSING_AUTH": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_FACILITY_NOT_FOUND": 404,
    "ERR_SUPPLIER_NOT_FOUND": 404,
    "ERR_INGREDIENT_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_COA_NOT_FOUND": 404,
    "ERR_RUN_NOT_FOUND": 404,
    "ERR_HOLD_NOT_FOUND": 404,
    "ERR_CROSS_FACILITY_REFERENCE": 409,
    "ERR_DUPLICATE_LOT_CODE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_COA_NOT_PENDING": 409,
    "ERR_COA_ALLERGEN_UNDISCLOSED": 409,
    "ERR_COA_PATHOGEN_FAIL": 409,
    "ERR_COA_SHELF_LIFE_SHORT": 409,
    "ERR_COA_NOT_ACCEPTED": 409,
    "ERR_LOT_NOT_RECEIVED": 409,
    "ERR_LOT_ON_HOLD": 409,
    "ERR_LOT_EXPIRED": 409,
    "ERR_SUPPLIER_NOT_APPROVED": 403,
    "ERR_RUN_NOT_OPEN": 409,
    "ERR_NO_CONSUMED_LOTS": 409,
    "ERR_SOURCE_LOT_NOT_RELEASED": 409,
    "ERR_SOURCE_LOT_EXPIRED": 409,
    "ERR_INSUFFICIENT_LOT_QTY": 409,
    "ERR_FEFO_VIOLATION": 409,
    "ERR_READING_OUT_OF_ORDER": 409,
    "ERR_HOLD_NOT_ACTIVE": 409,
    "ERR_CLOCK_NOT_MONOTONIC": 409,
    "ERR_ZONE_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_INVALID_INTERVAL": 409,
    "ERR_ZONE_CAPACITY_EXCEEDED": 409,
}


def err(error_id: str, message: str = "") -> APIError:
    return APIError(error_id, ERROR_CATALOG[error_id], message or error_id)
