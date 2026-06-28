"""Error catalog (SCAFFOLD §1.6 / PRD §5). Each error carries an error_id,
HTTP status, and a human-readable message."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog: error_id -> http status
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_NOT_RESOURCE_OWNER = ("ERR_NOT_RESOURCE_OWNER", 403)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_REPORTS_NOT_FINALIZED = ("ERR_REPORTS_NOT_FINALIZED", 409)
ERR_RELATIVE_FINDER_NOT_OPTED_IN = ("ERR_RELATIVE_FINDER_NOT_OPTED_IN", 422)
ERR_PURGE_IN_PROGRESS = ("ERR_PURGE_IN_PROGRESS", 409)
ERR_RETEST_NOT_ELIGIBLE = ("ERR_RETEST_NOT_ELIGIBLE", 422)
ERR_SAMPLE_NOT_GENOTYPABLE = ("ERR_SAMPLE_NOT_GENOTYPABLE", 422)
ERR_SUBSCRIPTION_EXISTS = ("ERR_SUBSCRIPTION_EXISTS", 409)
ERR_GRACE_NOT_ELAPSED = ("ERR_GRACE_NOT_ELAPSED", 409)
ERR_INVALID_RANGE = ("ERR_INVALID_RANGE", 422)
ERR_HEALTH_NOT_INCLUDED = ("ERR_HEALTH_NOT_INCLUDED", 422)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_INVALID_TOKEN = ("ERR_INVALID_TOKEN", 404)
ERR_UPGRADE_NOT_ALLOWED = ("ERR_UPGRADE_NOT_ALLOWED", 422)


def err(spec, message=None):
    error_id, status = spec
    return ApiError(error_id, status, message)
