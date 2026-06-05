"""Custom error class + the complete error catalog (scaffold §1.6 / PRD §5).

Each constant is a (error_id, http_status) tuple. raise_err(SPEC, msg) raises
an ApiError carrying both, which the global handler renders into the standard
error envelope.
"""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = ""):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


# Error catalog — exact IDs and HTTP statuses from PRD §5 / scaffold §1.6.
ERR_UNAUTHENTICATED        = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE         = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_RESOURCE_OWNER     = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_NOT_FOUND              = ("ERR_NOT_FOUND", 404)
ERR_INVALID_STATE          = ("ERR_INVALID_STATE", 409)
ERR_STALE_ACCOUNT_VERSION  = ("ERR_STALE_ACCOUNT_VERSION", 412)
ERR_CROSS_ACCOUNT_REFERENCE = ("ERR_CROSS_ACCOUNT_REFERENCE", 409)
ERR_RATING_BLOCKED         = ("ERR_RATING_BLOCKED", 403)
ERR_CURFEW_BLOCKED         = ("ERR_CURFEW_BLOCKED", 409)
ERR_DAILY_LIMIT_EXCEEDED   = ("ERR_DAILY_LIMIT_EXCEEDED", 409)
ERR_DEVICE_BUSY            = ("ERR_DEVICE_BUSY", 409)
ERR_HD_NOT_ALLOWED         = ("ERR_HD_NOT_ALLOWED", 409)
ERR_TITLE_NOT_DOWNLOADABLE = ("ERR_TITLE_NOT_DOWNLOADABLE", 409)
ERR_DUPLICATE              = ("ERR_DUPLICATE", 409)
ERR_CONCURRENT_CAP_REACHED = ("ERR_CONCURRENT_CAP_REACHED", 409)
ERR_DOWNLOAD_QUOTA_REACHED = ("ERR_DOWNLOAD_QUOTA_REACHED", 409)
ERR_PROFILE_CAP_REACHED    = ("ERR_PROFILE_CAP_REACHED", 409)
ERR_DEVICE_CAP_REACHED     = ("ERR_DEVICE_CAP_REACHED", 409)
ERR_INSUFFICIENT_CREDIT    = ("ERR_INSUFFICIENT_CREDIT", 402)
ERR_INVITE_EXPIRED         = ("ERR_INVITE_EXPIRED", 409)
ERR_INVALID_REQUEST        = ("ERR_INVALID_REQUEST", 400)


def raise_err(spec, message: str = ""):
    eid, http = spec
    raise ApiError(eid, http, message or eid)
