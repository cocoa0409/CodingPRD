"""Error classes and error ID constants (scaffold §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def unauthenticated(msg="Missing or invalid X-User-ID / X-User-Role headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def unauthorized(msg="Role not permitted for this operation"):
    return ApiError("ERR_UNAUTHORIZED", 403, msg)


def forbidden(msg="Acting identity does not match the resource owner"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_state(msg="Resource not in valid state for the requested transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def stale_version(msg="expected version does not match current resource version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def temporal(msg="Clock-based precondition failed"):
    return ApiError("ERR_TEMPORAL_VIOLATION", 422, msg)


def talent_conflict(msg="Talent has an overlapping ACTIVE conflict exclusion in this product_category"):
    return ApiError("ERR_TALENT_CONFLICT", 409, msg)


def session_overlap(msg="CONFIRMED session overlaps [start_at, end_at) for the same studio or talent"):
    return ApiError("ERR_SESSION_OVERLAP", 409, msg)


def patch_not_supported(msg="directed_patch=true but studio has_directed_patch=false"):
    return ApiError("ERR_PATCH_NOT_SUPPORTED", 422, msg)


def duplicate(msg="Uniqueness violation"):
    return ApiError("ERR_DUPLICATE", 409, msg)


def invalid_request(msg="Schema/enum/shape validation failed"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def pickup_prereq(msg="PICKUP requires a completed PRIMARY session; RETAKE requires revision_requested=true"):
    return ApiError("ERR_PICKUP_PREREQUISITE", 422, msg)


def fiscal(msg="Buyout computed non-positive, or usage-terms payload inconsistent with usage_type"):
    return ApiError("ERR_FISCAL_INVALID", 422, msg)
