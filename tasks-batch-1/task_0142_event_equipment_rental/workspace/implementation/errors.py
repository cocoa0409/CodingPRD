"""Custom error class and the full error catalog (scaffold §1.6 / PRD §5).

Error IDs and HTTP status codes are exactly as the scaffold §1.6 and PRD §5
catalog list them — do not rename.
"""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


# (error_id, http_status) tuples.
ERR_UNAUTHENTICATED        = ("ERR_UNAUTHENTICATED", 401)
ERR_UNAUTHORIZED           = ("ERR_UNAUTHORIZED", 403)
ERR_NOT_RESOURCE_OWNER     = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_NOT_FOUND              = ("ERR_NOT_FOUND", 404)
ERR_VALIDATION             = ("ERR_VALIDATION", 400)
ERR_INVALID_STATE          = ("ERR_INVALID_STATE", 409)
ERR_ORDER_EMPTY            = ("ERR_ORDER_EMPTY", 422)
ERR_COI_REQUIRED           = ("ERR_COI_REQUIRED", 422)
ERR_INVENTORY_UNAVAILABLE  = ("ERR_INVENTORY_UNAVAILABLE", 409)
ERR_CREW_WINDOW_CONFLICT   = ("ERR_CREW_WINDOW_CONFLICT", 409)
ERR_MAX_ATTEMPTS_EXCEEDED  = ("ERR_MAX_ATTEMPTS_EXCEEDED", 422)
ERR_DELIVERY_NOT_COMPLETED = ("ERR_DELIVERY_NOT_COMPLETED", 409)
ERR_NOT_RETURNED           = ("ERR_NOT_RETURNED", 409)
ERR_FORFEIT_EXCEEDS_HELD   = ("ERR_FORFEIT_EXCEEDS_HELD", 422)
ERR_NO_WEATHER_EVENT       = ("ERR_NO_WEATHER_EVENT", 422)
ERR_VENUE_REQUIRED         = ("ERR_VENUE_REQUIRED", 422)
ERR_INVALID_COVERAGE_WINDOW= ("ERR_INVALID_COVERAGE_WINDOW", 422)
ERR_INVALID_EVENT_WINDOW   = ("ERR_INVALID_EVENT_WINDOW", 422)
ERR_STALE_VERSION          = ("ERR_STALE_VERSION", 412)
ERR_LINE_NOT_DRAFT         = ("ERR_LINE_NOT_DRAFT", 409)
ERR_INACTIVE_ITEM          = ("ERR_INACTIVE_ITEM", 422)


def raise_err(spec, message: str = ""):
    eid, http = spec
    raise ApiError(eid, http, message or eid)
