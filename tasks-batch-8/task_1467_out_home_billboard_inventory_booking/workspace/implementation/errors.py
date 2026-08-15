"""Error type carrying the scaffold error catalog identifiers."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Convenience constructors (ids fixed by SCAFFOLD.yaml table 6 / PRD section 5)
def err_invalid_request(msg):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_insufficient(msg="Role not permitted for this endpoint or transition"):
    return ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403, msg)


def err_invalid_state(msg):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_stale(msg="expected version does not match the current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)
