"""Error catalogue (§5 / scaffold §1.6) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error IDs with their HTTP status, exactly as the PRD §5 catalogue declares.
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_DUPLICATE_RESOURCE = ("ERR_DUPLICATE_RESOURCE", 409)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_RISK_TRANSFER_REQUIRED = ("ERR_RISK_TRANSFER_REQUIRED", 409)
ERR_BACKUP_SAME_PROVIDER = ("ERR_BACKUP_SAME_PROVIDER", 409)
ERR_PROVIDER_AT_CAPACITY = ("ERR_PROVIDER_AT_CAPACITY", 409)
ERR_PROVIDER_WINDOW_OVERLAP = ("ERR_PROVIDER_WINDOW_OVERLAP", 409)
ERR_ROOM_DOUBLE_BOOKED = ("ERR_ROOM_DOUBLE_BOOKED", 409)
ERR_INVALID_INTERVAL = ("ERR_INVALID_INTERVAL", 422)
ERR_CLAIM_AMOUNTS_INVALID = ("ERR_CLAIM_AMOUNTS_INVALID", 422)
ERR_KIT_OUT_OF_STOCK = ("ERR_KIT_OUT_OF_STOCK", 409)
ERR_OVERPAYMENT = ("ERR_OVERPAYMENT", 409)
ERR_NO_BALANCE = ("ERR_NO_BALANCE", 409)
ERR_POSTPARTUM_INCOMPLETE = ("ERR_POSTPARTUM_INCOMPLETE", 409)
ERR_NO_ACTIVE_BOOKING = ("ERR_NO_ACTIVE_BOOKING", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_CLAIM_HAS_PLAN = ("ERR_CLAIM_HAS_PLAN", 409)


def err(spec, message=None):
    """Build an ApiError from one of the (id, http) tuples above."""
    return ApiError(spec[0], spec[1], message)
