"""Error definitions and exceptions for the Smart Parking Lot API."""


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Canonical error catalog from PRD §5 / SCAFFOLD 1.6
ERROR_CATALOG = {
    "ERR_MISSING_AUTH": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_BAD_REQUEST": 400,
    "ERR_VERSION_CONFLICT": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_SPACE_OCCUPIED": 409,
    "ERR_SPACE_NOT_BOOKABLE": 409,
    "ERR_RESERVATION_OVERLAP": 409,
    "ERR_NO_SPACE_AVAILABLE": 409,
    "ERR_INVALID_RESERVATION_WINDOW": 422,
    "ERR_VEHICLE_HAS_OPEN_VIOLATIONS": 409,
    "ERR_VEHICLE_ALREADY_BOUND": 409,
    "ERR_CARD_BINDING_LIMIT": 409,
    "ERR_CARD_EXPIRED": 409,
    "ERR_INVALID_CARD_TRANSFER": 422,
    "ERR_INSUFFICIENT_BALANCE": 402,
    "ERR_REFUND_WINDOW_EXPIRED": 422,
    "ERR_PHOTO_REQUIRED": 422,
    "ERR_EXEMPT_VEHICLE": 422,
    "ERR_REASON_REQUIRED": 422,
    "ERR_DUPLICATE_EXTERNAL_REF": 409,
    "ERR_VEHICLE_NOT_BOUND": 409,
}


def err(error_id: str, message: str = "") -> APIError:
    """Construct an APIError using the catalog HTTP status."""
    if error_id not in ERROR_CATALOG:
        # Treat unknowns as bad-request; should never happen in practice.
        return APIError(error_id, message or error_id, 400)
    return APIError(error_id, message or error_id, ERROR_CATALOG[error_id])
