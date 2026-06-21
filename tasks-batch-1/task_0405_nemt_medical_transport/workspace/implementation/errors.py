"""Error catalog and the ApiError exception (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http status
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 422,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_NOT_OWNER": 403,
    "ERR_MEMBER_INELIGIBLE": 409,
    "ERR_LOS_NOT_AUTHORIZED": 409,
    "ERR_MODALITY_MISMATCH": 409,
    "ERR_NO_BROKER_AVAILABLE": 409,
    "ERR_ASSIGNMENT_EXISTS": 409,
    "ERR_LEG_SEQUENCE_VIOLATION": 409,
    "ERR_RECON_INCOMPLETE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_DEPENDENCY_EXISTS": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)
