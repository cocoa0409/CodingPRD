"""Error catalog: error ids + HTTP statuses, and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error id constants (Table 6 / PRD section 5)
ERR_MISSING_CONTEXT = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"   # 400
ERR_FORBIDDEN = "ERR_FORBIDDEN_FOR_ROLE"                             # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                      # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                          # 400
ERR_STALE_VERSION = "ERR_STALE_VERSION"                              # 412
ERR_INVALID_STATE = "ERR_INVALID_STATE"                              # 409
ERR_SOD = "ERR_SEGREGATION_OF_DUTIES"                                # 403
ERR_AUTH_NOT_SATISFIED = "ERR_AUTH_NOT_SATISFIED"                    # 409
ERR_GFE_DEADLINE_MISSED = "ERR_GFE_DEADLINE_MISSED"                  # 409
ERR_SNAPSHOT_STALE = "ERR_SNAPSHOT_STALE"                            # 409
ERR_UNKNOWN_CPT_CODE = "ERR_UNKNOWN_CPT_CODE"                        # 422
ERR_SNAPSHOT_PATIENT_MISMATCH = "ERR_SNAPSHOT_PATIENT_MISMATCH"      # 422
ERR_NO_ACTIVE_CONTRACT = "ERR_NO_ACTIVE_CONTRACT"                    # 422
ERR_RATE_NOT_FOUND = "ERR_RATE_NOT_FOUND"                            # 422
ERR_DUPLICATE_MRN = "ERR_DUPLICATE_MRN"                              # 409
ERR_RATE_WINDOW_OVERLAP = "ERR_RATE_WINDOW_OVERLAP"                  # 409
ERR_AUTH_ALREADY_COVERED = "ERR_AUTH_ALREADY_COVERED"                # 409
ERR_ESTIMATE_LOCKED = "ERR_ESTIMATE_LOCKED"                          # 409
ERR_MEDICAL_NECESSITY_CONFLICT = "ERR_MEDICAL_NECESSITY_CONFLICT"    # 422
ERR_NO_ACCEPTED_ESTIMATE = "ERR_NO_ACCEPTED_ESTIMATE"                # 409
ERR_ESCALATION_REQUIRED = "ERR_ESCALATION_REQUIRED"                  # 409
ERR_ESCALATION_PENDING = "ERR_ESCALATION_PENDING"                    # 409
ERR_DEPOSIT_SHORTFALL = "ERR_DEPOSIT_SHORTFALL"                      # 409
ERR_PAYMENT_EXCEEDS_OUTSTANDING = "ERR_PAYMENT_EXCEEDS_OUTSTANDING"  # 422
ERR_CURE_INSUFFICIENT = "ERR_CURE_INSUFFICIENT"                      # 409


def bad_request(msg):
    return ApiError(ERR_INVALID_REQUEST, msg, 400)


def not_found(msg="resource not found"):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def invalid_state(msg="resource is in a state that does not allow this transition"):
    return ApiError(ERR_INVALID_STATE, msg, 409)
