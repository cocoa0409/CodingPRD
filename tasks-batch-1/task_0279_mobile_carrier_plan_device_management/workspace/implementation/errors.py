"""Error catalog — every id and HTTP status traces to PRD §5 / SCAFFOLD §1.6."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# (error_id, http_status) — verbatim from PRD §5 Error Code Catalogue.
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_ACCOUNT_OWNER = ("ERR_NOT_ACCOUNT_OWNER", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_FK_NOT_FOUND = ("ERR_FK_NOT_FOUND", 422)
ERR_VALIDATION = ("ERR_VALIDATION", 422)
ERR_STALE_ACCOUNT_VERSION = ("ERR_STALE_ACCOUNT_VERSION", 412)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_PLAN_RETIRED = ("ERR_PLAN_RETIRED", 409)
ERR_SIM_NOT_ISSUED = ("ERR_SIM_NOT_ISSUED", 409)
ERR_ACCOUNT_NOT_ACTIVE = ("ERR_ACCOUNT_NOT_ACTIVE", 409)
ERR_NUMBER_IN_USE = ("ERR_NUMBER_IN_USE", 409)
ERR_PORT_IN_PROGRESS = ("ERR_PORT_IN_PROGRESS", 409)
ERR_PORT_NOT_REVERTABLE = ("ERR_PORT_NOT_REVERTABLE", 409)
ERR_INVALID_WINDOW = ("ERR_INVALID_WINDOW", 422)
ERR_ADDON_OVERLAP = ("ERR_ADDON_OVERLAP", 409)
ERR_ADDON_WINDOW_NOT_STARTED = ("ERR_ADDON_WINDOW_NOT_STARTED", 409)
ERR_USAGE_OUTSIDE_CYCLE = ("ERR_USAGE_OUTSIDE_CYCLE", 422)
ERR_DEVICE_UNAVAILABLE = ("ERR_DEVICE_UNAVAILABLE", 409)
ERR_RECONNECT_BLOCKED = ("ERR_RECONNECT_BLOCKED", 409)
ERR_CYCLE_NOT_ENDED = ("ERR_CYCLE_NOT_ENDED", 409)


def err(spec, message=None):
    """Raise an ApiError from a (error_id, http_status) spec tuple."""
    error_id, http_status = spec
    raise ApiError(error_id, http_status, message)
