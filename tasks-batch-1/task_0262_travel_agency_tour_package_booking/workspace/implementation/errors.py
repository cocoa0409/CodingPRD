"""Error catalog and the ApiError exception type."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# HTTP status per error_id (Table 1.6 / PRD §5)
ERROR_STATUS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_REFERENCE": 422,
    "ERR_DUPLICATE_EMAIL": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_INVALID_INTERVAL": 422,
    "ERR_COMPONENT_OVERLAP": 409,
    "ERR_SUPPLIER_CAPACITY_CONFLICT": 409,
    "ERR_PACKAGE_NOT_PUBLISHED": 409,
    "ERR_PACKAGE_HAS_OPEN_BOOKINGS": 409,
    "ERR_NO_TRAVELERS": 409,
    "ERR_NO_COMPONENTS": 409,
    "ERR_COMPONENTS_NOT_CONFIRMED": 409,
    "ERR_DEPOSIT_NOT_SETTLED": 409,
    "ERR_OVERPAYMENT": 422,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS.get(error_id, 400), message)
