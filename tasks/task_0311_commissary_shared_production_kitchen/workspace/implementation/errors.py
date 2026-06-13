"""Error classes and the error-id -> HTTP status catalogue (PRD section 5)."""


class ApiError(Exception):
    """Carries an error_id, a human-readable message, and an HTTP status."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or ERROR_MESSAGES.get(error_id, error_id)
        self.http_status = http_status or HTTP_STATUS.get(error_id, 400)
        super().__init__(self.message)


# PRD section 5 — Error Code Catalogue.
HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN_NOT_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_INTERVAL": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_MEMBER_NOT_ACTIVE": 409,
    "ERR_MEMBER_HAS_OPEN_OBLIGATIONS": 409,
    "ERR_STATION_OUT_OF_SERVICE": 409,
    "ERR_PEAK_REQUIRES_PREMIUM": 409,
    "ERR_BOOKING_OVERLAP": 409,
    "ERR_RECIPE_EMPTY": 409,
    "ERR_RECIPE_NOT_PUBLISHED": 409,
    "ERR_RECIPE_IN_USE": 409,
    "ERR_INSUFFICIENT_STOCK": 409,
    "ERR_BATCH_NOT_COMPLETED": 409,
    "ERR_ALLERGEN_CONFLICT": 409,
    "ERR_STORAGE_CAPACITY_EXCEEDED": 409,
    "ERR_UNIT_QUARANTINED": 409,
    "ERR_UNIT_NOT_RECOVERED": 409,
    "ERR_INSUFFICIENT_WALLET": 402,
    "ERR_VALIDATION": 422,
}

ERROR_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or invalid authentication headers.",
    "ERR_UNAUTHORIZED": "The acting role is not permitted to perform this operation.",
    "ERR_FORBIDDEN_NOT_OWNER": "The acting member does not own this resource.",
    "ERR_NOT_FOUND": "The referenced resource does not exist.",
    "ERR_INVALID_REQUEST": "The request body is malformed or missing required fields.",
    "ERR_INVALID_INTERVAL": "end_utc must be strictly later than start_utc.",
    "ERR_STALE_VERSION": "expected_member_version does not match the member's current version.",
    "ERR_INVALID_STATE": "The resource is not in a valid state for the requested transition.",
    "ERR_MEMBER_NOT_ACTIVE": "The acting member is not ACTIVE.",
    "ERR_MEMBER_HAS_OPEN_OBLIGATIONS": "The member still has open obligations.",
    "ERR_STATION_OUT_OF_SERVICE": "The station is OUT_OF_SERVICE.",
    "ERR_PEAK_REQUIRES_PREMIUM": "Peak bookings require a PREMIUM plan tier.",
    "ERR_BOOKING_OVERLAP": "The booking interval overlaps an existing booking on the station.",
    "ERR_RECIPE_EMPTY": "The recipe has no components.",
    "ERR_RECIPE_NOT_PUBLISHED": "The recipe is not PUBLISHED.",
    "ERR_RECIPE_IN_USE": "The recipe is pinned or referenced by a batch.",
    "ERR_INSUFFICIENT_STOCK": "Ingredient stock is insufficient for the batch.",
    "ERR_BATCH_NOT_COMPLETED": "A packed batch is not COMPLETED.",
    "ERR_ALLERGEN_CONFLICT": "The packed allergens intersect the required allergen-free set.",
    "ERR_STORAGE_CAPACITY_EXCEEDED": "Requested storage slots exceed available capacity.",
    "ERR_UNIT_QUARANTINED": "A storage unit involved is QUARANTINED.",
    "ERR_UNIT_NOT_RECOVERED": "The latest temperature reading is still out of range.",
    "ERR_INSUFFICIENT_WALLET": "The wallet balance is below the computed charge.",
    "ERR_VALIDATION": "Query parameter validation failed.",
}
