"""Domain error classes and error_id constants (scaffold §1.6 / PRD §5)."""


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id constants — verbatim from scaffold §1.6 / PRD §5
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_FK_INVALID = "ERR_FK_INVALID"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_WITHIN_WAITING_PERIOD = "ERR_WITHIN_WAITING_PERIOD"
ERR_PRE_EXISTING_EXCLUDED = "ERR_PRE_EXISTING_EXCLUDED"
ERR_POLICY_YEAR_CLOSED = "ERR_POLICY_YEAR_CLOSED"
ERR_CLAIM_NOT_READY = "ERR_CLAIM_NOT_READY"
ERR_WELLNESS_RIDER_REQUIRED = "ERR_WELLNESS_RIDER_REQUIRED"
ERR_STALE_POLICY_YEAR_VERSION = "ERR_STALE_POLICY_YEAR_VERSION"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_CLAIM_REVERSED = "ERR_CLAIM_REVERSED"
