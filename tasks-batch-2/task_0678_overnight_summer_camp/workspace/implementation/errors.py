"""Error classes and error ID constants for the Overnight Summer Camp API.

Error IDs and HTTP statuses are taken verbatim from SCAFFOLD.yaml §1.6 /
PRD §5. Never invent or rename an error ID.
"""


class ApiError(Exception):
    """An application error carrying an error_id, message, and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Auth
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                          # 400
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                          # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"                            # 403
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"                    # 403
# Existence / referential / state / concurrency
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                     # 404
ERR_REFERENTIAL_MISMATCH = "ERR_REFERENTIAL_MISMATCH"                # 409
ERR_INVALID_STATE = "ERR_INVALID_STATE"                             # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                             # 412
# Session lifecycle / enrollment
ERR_ENROLLMENT_CLOSED = "ERR_ENROLLMENT_CLOSED"                      # 409
ERR_NO_CABINS = "ERR_NO_CABINS"                                     # 409
ERR_SESSION_FULL = "ERR_SESSION_FULL"                               # 409
ERR_SESSION_NOT_STARTED = "ERR_SESSION_NOT_STARTED"                  # 422
ERR_SESSION_NOT_ENDED = "ERR_SESSION_NOT_ENDED"                      # 422
ERR_SESSION_UNDERSTAFFED = "ERR_SESSION_UNDERSTAFFED"                # 422
ERR_SESSION_RUNNING_NO_WITHDRAW = "ERR_SESSION_RUNNING_NO_WITHDRAW"  # 409
ERR_VISITING_DAY_OUT_OF_RANGE = "ERR_VISITING_DAY_OUT_OF_RANGE"      # 422
# Health / infirmary
ERR_HEALTH_FORM_MISSING = "ERR_HEALTH_FORM_MISSING"                  # 422
ERR_EPIPEN_REQUIRED = "ERR_EPIPEN_REQUIRED"                          # 422
ERR_HEALTH_NOT_CLEARED = "ERR_HEALTH_NOT_CLEARED"                    # 422
ERR_SWIM_TEST_REQUIRED = "ERR_SWIM_TEST_REQUIRED"                    # 422
# Eligibility / cabin / staffing
ERR_NO_ELIGIBLE_CABIN = "ERR_NO_ELIGIBLE_CABIN"                      # 422
ERR_CABIN_GENDER_MISMATCH = "ERR_CABIN_GENDER_MISMATCH"              # 422
ERR_CABIN_AGE_MISMATCH = "ERR_CABIN_AGE_MISMATCH"                    # 422
ERR_CABIN_FULL = "ERR_CABIN_FULL"                                   # 409
ERR_CABIN_UNDERSTAFFED = "ERR_CABIN_UNDERSTAFFED"                    # 422
ERR_NO_BUNK_ASSIGNED = "ERR_NO_BUNK_ASSIGNED"                        # 409
ERR_STAFF_NOT_CLEARED = "ERR_STAFF_NOT_CLEARED"                      # 422
# Fiscal
ERR_DEPOSIT_AMOUNT_MISMATCH = "ERR_DEPOSIT_AMOUNT_MISMATCH"          # 422
ERR_OFFER_EXPIRED = "ERR_OFFER_EXPIRED"                             # 409
ERR_AID_EXCEEDS_TUITION = "ERR_AID_EXCEEDS_TUITION"                  # 422
ERR_CANTEEN_INSUFFICIENT_FUNDS = "ERR_CANTEEN_INSUFFICIENT_FUNDS"    # 422
# Activity scheduling
ERR_ACTIVITY_TIME_CONFLICT = "ERR_ACTIVITY_TIME_CONFLICT"            # 422
ERR_ACTIVITY_FULL = "ERR_ACTIVITY_FULL"                             # 409
