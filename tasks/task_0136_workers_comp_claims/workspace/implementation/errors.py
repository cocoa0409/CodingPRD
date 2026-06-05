"""Domain error classes and error_id constants (scaffold §1.6 / PRD §5)."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id constants — verbatim from scaffold §1.6 / PRD §5
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                  # 403
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_FROI_NOT_ACKNOWLEDGED = "ERR_FROI_NOT_ACKNOWLEDGED"  # 409
ERR_INVALID_MTC = "ERR_INVALID_MTC"                   # 422
ERR_RATING_NOT_FINALIZED = "ERR_RATING_NOT_FINALIZED"  # 409
ERR_STATUTE_EXPIRED = "ERR_STATUTE_EXPIRED"           # 422
ERR_IME_WINDOW_CONFLICT = "ERR_IME_WINDOW_CONFLICT"   # 409
ERR_RTW_WINDOW_CONFLICT = "ERR_RTW_WINDOW_CONFLICT"   # 409
ERR_DUPLICATE_RESOURCE = "ERR_DUPLICATE_RESOURCE"     # 409
ERR_RESERVE_INSUFFICIENT = "ERR_RESERVE_INSUFFICIENT"  # 422
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"           # 400
ERR_STALE_CLAIM_VERSION = "ERR_STALE_CLAIM_VERSION"   # 412
