"""Error catalog (PRD §5 / scaffold §1.6).

Every error carries its error_id and HTTP status verbatim from the catalog.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# error_id -> http status (PRD §5 error code catalogue)
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_OWNER": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 422,
    "ERR_REFERENTIAL_INTEGRITY": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_EMPTY_PROPOSAL": 409,
    "ERR_PROPOSAL_ALREADY_ACCEPTED": 409,
    "ERR_RACK_REQUIRED": 409,
    "ERR_RACK_CAPACITY_EXCEEDED": 409,
    "ERR_IP_POOL_EXHAUSTED": 409,
    "ERR_FIRMWARE_REQUIRED": 409,
    "ERR_FIRMWARE_NOT_NEWER": 409,
    "ERR_NOT_LATEST_FIRMWARE": 409,
    "ERR_EMPTY_SCENE": 409,
    "ERR_SCENE_DEVICE_MISMATCH": 422,
    "ERR_NO_CONTROLLER_IN_SCENE": 409,
    "ERR_SCENE_DEVICE_NOT_ONLINE": 409,
    "ERR_UNDERSTAFFED_VISIT": 409,
    "ERR_CERT_TOO_LOW": 409,
    "ERR_VISIT_NOT_DUE": 409,
    "ERR_CREW_TIME_CONFLICT": 409,
    "ERR_VISIT_TIME_CONFLICT": 409,
    "ERR_CREW_DAILY_CAP_EXCEEDED": 409,
    "ERR_CREW_REGION_MISMATCH": 422,
    "ERR_CREW_INACTIVE": 422,
    "ERR_DEVICES_NOT_ONLINE": 409,
    "ERR_NO_DEPLOYED_SCENE": 409,
    "ERR_DEVICE_NOT_FAULTED": 409,
    "ERR_DEVICE_HAS_OPEN_RMA": 409,
    "ERR_CONTRACT_NOT_ACTIVE": 409,
    "ERR_CONTRACT_ALREADY_ACTIVE": 409,
    "ERR_CONTRACT_HAS_OPEN_RMA": 409,
    "ERR_OPEN_CHANGE_ORDERS": 409,
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
