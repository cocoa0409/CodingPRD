"""Error classes and error ID constants (from SCAFFOLD error catalog)."""

ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"        # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"              # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                    # 404
ERR_DUPLICATE = "ERR_DUPLICATE"                    # 409
ERR_INVALID_STATE = "ERR_INVALID_STATE"            # 409
ERR_DMA_FROZEN = "ERR_DMA_FROZEN"                  # 409
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 403
ERR_WINDOW_CONFLICT = "ERR_WINDOW_CONFLICT"        # 409
ERR_VALIDATION = "ERR_VALIDATION"                  # 422
ERR_MISSING_PREREQUISITE = "ERR_MISSING_PREREQUISITE"  # 422
ERR_BCR_BELOW_THRESHOLD = "ERR_BCR_BELOW_THRESHOLD"    # 422
ERR_BALANCE_INCONSISTENT = "ERR_BALANCE_INCONSISTENT"  # 422
ERR_STALE_VERSION = "ERR_STALE_VERSION"            # 412
ERR_CHILDREN_OPEN = "ERR_CHILDREN_OPEN"            # 409


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message
