"""API error type. Error IDs and HTTP statuses come from the scaffold/PRD
error catalogue."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, http_status, message):
    return ApiError(error_id, http_status, message)


# Convenience raisers -------------------------------------------------------

def not_found(msg="Resource not found"):
    raise err("ERR_NOT_FOUND", 404, msg)


def invalid_request(msg):
    raise err("ERR_INVALID_REQUEST", 400, msg)


def invalid_enum(msg):
    raise err("ERR_INVALID_ENUM_VALUE", 400, msg)
