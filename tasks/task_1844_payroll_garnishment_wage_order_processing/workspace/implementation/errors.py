"""Error catalog — exact error ids and HTTP statuses from the PRD/scaffold."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def fail(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                  # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"                    # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                              # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                  # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"                      # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                      # 412
ERR_CASE_NUMBER_PATTERN = "ERR_CASE_NUMBER_PATTERN"          # 422
ERR_STATE_RULE_MISSING = "ERR_STATE_RULE_MISSING"            # 422
ERR_AUTHORITY_MISMATCH = "ERR_AUTHORITY_MISMATCH"            # 422
ERR_DUPLICATE_ACTIVE_ORDER = "ERR_DUPLICATE_ACTIVE_ORDER"    # 409
ERR_EMPLOYEE_TERMINATED_INELIGIBLE = "ERR_EMPLOYEE_TERMINATED_INELIGIBLE"  # 409
ERR_PERIOD_OVERLAP = "ERR_PERIOD_OVERLAP"                    # 409
ERR_INVALID_DEDUCTIONS = "ERR_INVALID_DEDUCTIONS"            # 422
ERR_RUN_EMPTY = "ERR_RUN_EMPTY"                              # 422
ERR_RUN_HAS_POSTED_EVENTS = "ERR_RUN_HAS_POSTED_EVENTS"      # 409
ERR_REFUND_EXCEEDS_WITHHELD = "ERR_REFUND_EXCEEDS_WITHHELD"  # 422
ERR_SUSPEND_LIMIT_EXCEEDED = "ERR_SUSPEND_LIMIT_EXCEEDED"    # 409
ERR_REMITTANCE_EMPTY = "ERR_REMITTANCE_EMPTY"                # 409
ERR_NO_REMITTABLE_EVENTS = "ERR_NO_REMITTABLE_EVENTS"        # 409
ERR_DUPLICATE_REMITTANCE = "ERR_DUPLICATE_REMITTANCE"        # 409
ERR_AUDIT_CHAIN_BROKEN = "ERR_AUDIT_CHAIN_BROKEN"            # 409
