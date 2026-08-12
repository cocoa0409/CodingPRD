"""Error types and catalog."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id: str, http_status: int, message: str) -> ApiError:
    return ApiError(error_id, http_status, message)
