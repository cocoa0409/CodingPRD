"""Error classes and error ID constants for the TNR program API.

Every error_id below is taken verbatim from SCAFFOLD.yaml §1.6 / PRD §5.
"""

# --- Error catalog (SCAFFOLD.yaml §1.6, PRD §5) ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                        # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"                # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                # 412
ERR_NOT_RELEASE_READY = "ERR_NOT_RELEASE_READY"        # 422
ERR_NOT_A_KITTEN = "ERR_NOT_A_KITTEN"                  # 422
ERR_OWNERSHIP_MISMATCH = "ERR_OWNERSHIP_MISMATCH"      # 403
ERR_UNIQUENESS_VIOLATION = "ERR_UNIQUENESS_VIOLATION"  # 409
ERR_TEMPORAL_CONFLICT = "ERR_TEMPORAL_CONFLICT"        # 422
ERR_CLINIC_DAY_FULL = "ERR_CLINIC_DAY_FULL"            # 409
ERR_MONTHLY_CAP_EXCEEDED = "ERR_MONTHLY_CAP_EXCEEDED"  # 402
ERR_VOUCHER_NOT_USABLE = "ERR_VOUCHER_NOT_USABLE"      # 402
ERR_FOSTER_HOME_FULL = "ERR_FOSTER_HOME_FULL"          # 409
ERR_SURVEY_INCONSISTENT = "ERR_SURVEY_INCONSISTENT"    # 422
ERR_DAY_HAS_BOOKINGS = "ERR_DAY_HAS_BOOKINGS"          # 409
ERR_NOTHING_TO_EXPIRE = "ERR_NOTHING_TO_EXPIRE"        # 422
ERR_COLONY_NOT_DISSOLVABLE = "ERR_COLONY_NOT_DISSOLVABLE"  # 409

# Request-level validation failure (missing/invalid fields). The PRD error
# catalogue defines no dedicated ID for malformed requests; the corner design
# pins "http status in {400, 422}" for such rejections.
ERR_VALIDATION = "ERR_VALIDATION"                      # 400


class ApiError(Exception):
    """Exception carrying the error envelope payload."""

    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def not_found(what="resource"):
    return ApiError(ERR_NOT_FOUND, 404, f"The requested {what} does not exist.")


def invalid_state(message):
    return ApiError(ERR_INVALID_STATE, 409, message)


def validation(message):
    return ApiError(ERR_VALIDATION, 400, message)
