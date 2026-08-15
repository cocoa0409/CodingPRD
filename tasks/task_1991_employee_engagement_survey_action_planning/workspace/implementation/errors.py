"""Error classes and error ID constants for the Engagement Survey API."""


class ApiError(Exception):
    """Exception carrying an error_id, human message, and HTTP status."""

    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error ID constants (from SCAFFOLD §1.6 / PRD §5)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                  # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"    # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"                # 409
ERR_CONFIDENTIALITY = "ERR_CONFIDENTIALITY"            # 403
ERR_DUTY_SEGREGATION = "ERR_DUTY_SEGREGATION"          # 403
ERR_DUPLICATE = "ERR_DUPLICATE"                        # 409
ERR_WINDOW_VIOLATION = "ERR_WINDOW_VIOLATION"          # 422
ERR_UNIT_CYCLE = "ERR_UNIT_CYCLE"                      # 422
ERR_THRESHOLD_INVERSION = "ERR_THRESHOLD_INVERSION"    # 422
ERR_CYCLE_ALREADY_OPEN = "ERR_CYCLE_ALREADY_OPEN"      # 409
ERR_INSUFFICIENT_ITEMS = "ERR_INSUFFICIENT_ITEMS"      # 422
ERR_STALE_VERSION = "ERR_STALE_VERSION"                # 412
ERR_VALIDATION = "ERR_VALIDATION"                      # 400
ERR_ANSWERS_INCOMPLETE = "ERR_ANSWERS_INCOMPLETE"      # 422
ERR_INVITE_OWNERSHIP = "ERR_INVITE_OWNERSHIP"          # 403
ERR_PLAN_OWNERSHIP = "ERR_PLAN_OWNERSHIP"              # 403
ERR_SNAPSHOT_NOT_PUBLISHED = "ERR_SNAPSHOT_NOT_PUBLISHED"  # 409
ERR_BENCHMARK_TOO_SMALL = "ERR_BENCHMARK_TOO_SMALL"    # 422
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"            # 400


def err(error_id, message, http_status):
    return ApiError(error_id, message, http_status)
