"""Domain error classes and the error-id catalogue (PRD §5)."""
from __future__ import annotations


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalogue: exact ids + http codes from PRD §5 / scaffold §1.6 -----
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                        # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"            # 422
ERR_STALE_VERSION = "ERR_STALE_VERSION"                # 412
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_EMPTY_HOUSEHOLD = "ERR_EMPTY_HOUSEHOLD"            # 409
ERR_NOT_VERIFIED = "ERR_NOT_VERIFIED"                  # 409
ERR_NO_ELIGIBLE_DETERMINATION = "ERR_NO_ELIGIBLE_DETERMINATION"  # 409
ERR_APPLICATION_NOT_APPROVED = "ERR_APPLICATION_NOT_APPROVED"    # 409
ERR_COVERAGE_OVERLAP = "ERR_COVERAGE_OVERLAP"          # 409
ERR_REDETERMINATION_WINDOW_OVERLAP = "ERR_REDETERMINATION_WINDOW_OVERLAP"  # 409
ERR_REDETERMINATION_IN_PROGRESS = "ERR_REDETERMINATION_IN_PROGRESS"        # 409
ERR_DETERMINATION_INELIGIBLE = "ERR_DETERMINATION_INELIGIBLE"  # 409
ERR_CONTINUOUS_COVERAGE_LOCK = "ERR_CONTINUOUS_COVERAGE_LOCK"  # 409
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"        # 409
ERR_NOT_TERMINATED = "ERR_NOT_TERMINATED"             # 409
