"""Error catalog: error_id -> HTTP status, plus the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_SOD_VIOLATION": 403,
    "ERR_OWNERSHIP_MISMATCH": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_DECISION_PAIR": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_PRIVILEGE_GATE": 409,
    "ERR_OFFICER_SUSPENDED": 409,
    "ERR_DIRECTOR_APPROVAL_REQUIRED": 403,
    "ERR_APPLICATION_LOCKED": 409,
    "ERR_SCOPE_OVERLAP": 409,
    "ERR_SELF_TEST_WINDOW_OVERLAP": 409,
    "ERR_PERIOD_GAP": 409,
    "ERR_PERIOD_OVERLAP": 409,
    "ERR_PERIOD_NOT_QUARTER": 422,
    "ERR_NO_IN_SCOPE_APPLICATIONS": 422,
    "ERR_APPLICATIONS_NOT_VALIDATED": 409,
    "ERR_STALE_DATASET": 409,
    "ERR_RUN_HAS_OPEN_FINDINGS": 409,
    "ERR_FINDINGS_OPEN": 409,
    "ERR_NO_CONFIRMED_MATCHED_PAIR": 409,
    "ERR_MATCH_NOT_COMPARABLE": 422,
    "ERR_EMPTY_CONTROL_POOL": 422,
    "ERR_CAP_ACTIVE": 409,
    "ERR_CAP_NOT_EXECUTING": 409,
    "ERR_CAP_BUDGET_EXCEEDED": 422,
    "ERR_PAYEE_NOT_IN_CAP_SCOPE": 422,
    "ERR_NO_SUBSTANTIATED_FINDING": 409,
    "ERR_REMEDIATION_OUTSTANDING": 409,
    "ERR_REPORT_NOT_READY": 409,
    "ERR_BENCHMARK_PERIOD_CONFLICT": 409,
}


def err(error_id, message):
    return ApiError(error_id, ERROR_STATUS[error_id], message)


def not_found(what="Resource"):
    return err("ERR_NOT_FOUND", "%s does not exist" % what)


def invalid_request(message):
    return err("ERR_INVALID_REQUEST", message)


def invalid_state(message):
    return err("ERR_INVALID_STATE", message)


def already_terminal(message):
    return err("ERR_ALREADY_TERMINAL", message)
