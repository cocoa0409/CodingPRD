"""Domain error class and error_id constants (scaffold §1.6 / PRD §5)."""
from __future__ import annotations


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id constants — verbatim from scaffold §1.6 / PRD §5
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                  # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404 (path)
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"    # 404 (body FK)
ERR_VEHICLE_NOT_OWNED = "ERR_VEHICLE_NOT_OWNED"        # 422
ERR_LINE_TYPE_FIELD_MISMATCH = "ERR_LINE_TYPE_FIELD_MISMATCH"  # 422
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_FITMENT_NOT_APPROVED = "ERR_FITMENT_NOT_APPROVED"  # 422
ERR_BAY_NOT_ALIGNMENT_CAPABLE = "ERR_BAY_NOT_ALIGNMENT_CAPABLE"  # 422
ERR_BAY_OUT_OF_SERVICE = "ERR_BAY_OUT_OF_SERVICE"     # 409
ERR_INVALID_INTERVAL = "ERR_INVALID_INTERVAL"         # 422
ERR_BAY_TIME_CONFLICT = "ERR_BAY_TIME_CONFLICT"       # 409
ERR_INSUFFICIENT_STOCK = "ERR_INSUFFICIENT_STOCK"     # 422
ERR_MILEAGE_EXCEEDED = "ERR_MILEAGE_EXCEEDED"         # 422
ERR_NOT_WORN_TO_BAR = "ERR_NOT_WORN_TO_BAR"           # 422
ERR_PAYMENT_REQUIRED = "ERR_PAYMENT_REQUIRED"         # 402
ERR_STALE_VERSION = "ERR_STALE_VERSION"               # 412
ERR_STALE_BAY_VERSION = "ERR_STALE_BAY_VERSION"       # 412
ERR_STALE_WORK_ORDER_VERSION = "ERR_STALE_WORK_ORDER_VERSION"  # 412
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"           # 422
ERR_NEGATIVE_STOCK = "ERR_NEGATIVE_STOCK"             # 422
