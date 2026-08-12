"""Error type carrying the catalog error_id and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- catalog ids ------------------------------------------------------------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                # 403
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412
ERR_LICENSE_NOT_ACTIVE = "ERR_LICENSE_NOT_ACTIVE"    # 409
ERR_LABEL_NOT_APPROVED = "ERR_LABEL_NOT_APPROVED"    # 409
ERR_LABEL_EXPIRED = "ERR_LABEL_EXPIRED"              # 409
ERR_PERMIT_EXPIRED = "ERR_PERMIT_EXPIRED"            # 409
ERR_PRESS_WINDOW_CONFLICT = "ERR_PRESS_WINDOW_CONFLICT"  # 409
ERR_RETURN_WINDOW_EXPIRED = "ERR_RETURN_WINDOW_EXPIRED"  # 409
ERR_NO_TANK_AVAILABLE = "ERR_NO_TANK_AVAILABLE"      # 409
ERR_ABV_OUT_OF_TOLERANCE = "ERR_ABV_OUT_OF_TOLERANCE"    # 409
ERR_INSUFFICIENT_FRUIT = "ERR_INSUFFICIENT_FRUIT"    # 409
ERR_BATCH_NOT_READY = "ERR_BATCH_NOT_READY"          # 409
ERR_INSUFFICIENT_VOLUME = "ERR_INSUFFICIENT_VOLUME"  # 409
ERR_LICENSE_CAP_EXCEEDED = "ERR_LICENSE_CAP_EXCEEDED"    # 409
ERR_INSUFFICIENT_INVENTORY = "ERR_INSUFFICIENT_INVENTORY"  # 409
ERR_CONTRACT_HAS_OPEN_LOTS = "ERR_CONTRACT_HAS_OPEN_LOTS"  # 409
ERR_PERIOD_NOT_CLOSED = "ERR_PERIOD_NOT_CLOSED"      # 409
ERR_DUPLICATE_REPORT = "ERR_DUPLICATE_REPORT"        # 409
ERR_DUPLICATE_SKU = "ERR_DUPLICATE_SKU"              # 409
ERR_DUPLICATE_LABEL_MARKET = "ERR_DUPLICATE_LABEL_MARKET"  # 409
# Fallback for malformed request bodies (not part of the PRD catalog).
ERR_VALIDATION = "ERR_VALIDATION"                    # 400


def not_found(what="resource"):
    return ApiError(ERR_NOT_FOUND, f"{what} not found", 404)


def invalid_state(msg):
    return ApiError(ERR_INVALID_STATE, msg, 409)


def validation(msg):
    return ApiError(ERR_VALIDATION, msg, 400)
