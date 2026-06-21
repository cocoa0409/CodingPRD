"""Error classes and error ID constants (from SCAFFOLD §1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http_status
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_NO_ACTIVE_CARD": 422,
    "ERR_NOT_ELIGIBLE": 422,
    "ERR_MEMBER_SUSPENDED": 409,
    "ERR_DAY_PASS_INVALID": 422,
    "ERR_LOUNGE_OVERFLOW": 409,
    "ERR_OVER_CAPACITY": 409,
    "ERR_SHOWER_UNAVAILABLE": 409,
    "ERR_SHOWER_CONFLICT": 409,
    "ERR_SETTLEMENT_NOT_PAYABLE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_REQUEST": 400,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_CATALOG[error_id], message)


# Convenience constructors -------------------------------------------------
def unauthenticated(msg=None):
    return err("ERR_UNAUTHENTICATED", msg)


def forbidden_role(msg=None):
    return err("ERR_FORBIDDEN_ROLE", msg)


def not_owner(msg=None):
    return err("ERR_NOT_RESOURCE_OWNER", msg)


def not_found(msg=None):
    return err("ERR_NOT_FOUND", msg)


def invalid_state(msg=None):
    return err("ERR_INVALID_STATE", msg)


def invalid_request(msg=None):
    return err("ERR_INVALID_REQUEST", msg)


def stale_version(msg=None):
    return err("ERR_STALE_VERSION", msg)
