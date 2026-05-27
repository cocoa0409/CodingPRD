"""Error class and error_id constants."""


class APIError(Exception):
    def __init__(self, error_id, http_status, message=None):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


# Error catalog (from SCAFFOLD §1.6 + PRD §5)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_FK_NOT_FOUND = "ERR_FK_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_EMPLOYEE_NOT_ACTIVE = "ERR_EMPLOYEE_NOT_ACTIVE"
ERR_SOD_VIOLATION = "ERR_SOD_VIOLATION"
ERR_GARNISHMENT_EXCEEDS_CCPA = "ERR_GARNISHMENT_EXCEEDS_CCPA"
ERR_NO_W4_ON_FILE = "ERR_NO_W4_ON_FILE"
ERR_SUPERSEDE_TARGET_INVALID = "ERR_SUPERSEDE_TARGET_INVALID"
ERR_PAY_PERIOD_OVERLAP = "ERR_PAY_PERIOD_OVERLAP"
ERR_GARNISHMENT_AGGREGATE_CAP = "ERR_GARNISHMENT_AGGREGATE_CAP"
ERR_REMITTANCE_AMOUNT_MISMATCH = "ERR_REMITTANCE_AMOUNT_MISMATCH"
ERR_OPEN_RUN_BLOCKS_CLOSE = "ERR_OPEN_RUN_BLOCKS_CLOSE"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"


def invalid_request(msg="invalid request"):
    return APIError(ERR_INVALID_REQUEST, 400, msg)


def not_found(msg="not found"):
    return APIError(ERR_NOT_FOUND, 404, msg)


def fk_not_found(msg="foreign key not found"):
    return APIError(ERR_FK_NOT_FOUND, 404, msg)


def invalid_state(msg="invalid state"):
    return APIError(ERR_INVALID_STATE, 409, msg)


def employee_not_active(msg="employee not active"):
    return APIError(ERR_EMPLOYEE_NOT_ACTIVE, 409, msg)


def forbidden(msg="forbidden"):
    return APIError(ERR_FORBIDDEN, 403, msg)


def unauthenticated(msg="unauthenticated"):
    return APIError(ERR_UNAUTHENTICATED, 401, msg)
