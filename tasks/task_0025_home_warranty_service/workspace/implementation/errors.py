"""Domain error classes and error_id constants (scaffold §1.6)."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id constants — verbatim from scaffold §1.6 / PRD §5
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_ITEM_NOT_ON_CONTRACT = "ERR_ITEM_NOT_ON_CONTRACT"
ERR_OUT_OF_COVERAGE = "ERR_OUT_OF_COVERAGE"
ERR_PRE_EXISTING_EXCLUDED = "ERR_PRE_EXISTING_EXCLUDED"
ERR_ITEM_LIMIT_EXCEEDED = "ERR_ITEM_LIMIT_EXCEEDED"
ERR_SCHEDULED_IN_PAST = "ERR_SCHEDULED_IN_PAST"
ERR_TECHNICIAN_DOUBLE_BOOKED = "ERR_TECHNICIAN_DOUBLE_BOOKED"
ERR_OPEN_CLAIMS_BLOCK_CANCEL = "ERR_OPEN_CLAIMS_BLOCK_CANCEL"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_PACKAGE_RETIRED = "ERR_PACKAGE_RETIRED"
