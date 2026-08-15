"""Error classes and error ID constants (from SCAFFOLD §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error IDs (exact strings from scaffold error catalog)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_VALIDATION = "ERR_VALIDATION"                    # 422
ERR_DUPLICATE = "ERR_DUPLICATE"                      # 409
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_QUARTER_LOCKED = "ERR_QUARTER_LOCKED"            # 409
ERR_CROSS_REIT_REFERENCE = "ERR_CROSS_REIT_REFERENCE"  # 422
ERR_INVALID_DATE_RANGE = "ERR_INVALID_DATE_RANGE"    # 422
ERR_QUARTER_OVERLAP = "ERR_QUARTER_OVERLAP"          # 409
ERR_REIT_SUSPENDED = "ERR_REIT_SUSPENDED"            # 409
ERR_FIVE_FIFTY_BLOCKED = "ERR_FIVE_FIFTY_BLOCKED"    # 409
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 403
ERR_REQUIREMENT_NOT_POSTED = "ERR_REQUIREMENT_NOT_POSTED"  # 409
ERR_DECLARATIONS_OPEN = "ERR_DECLARATIONS_OPEN"      # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412
ERR_SNAPSHOT_EMPTY = "ERR_SNAPSHOT_EMPTY"            # 422


def unauthenticated(message="Missing or unknown X-User-Role / X-User-ID headers"):
    return ApiError(ERR_UNAUTHENTICATED, message, 401)


def unauthorized(message="Role not permitted for this endpoint per RBAC"):
    return ApiError(ERR_UNAUTHORIZED, message, 403)


def not_found(message="Path id or FK body reference does not resolve"):
    return ApiError(ERR_NOT_FOUND, message, 404)


def validation(message="Required field missing, enum out of set, or numeric range violated"):
    return ApiError(ERR_VALIDATION, message, 422)


def duplicate(message="Uniqueness constraint violated"):
    return ApiError(ERR_DUPLICATE, message, 409)


def invalid_state(message="Transition requested from a state that does not list it"):
    return ApiError(ERR_INVALID_STATE, message, 409)


def quarter_locked(message="Data mutation attempted against a LOCKED quarter or FINALIZED snapshot"):
    return ApiError(ERR_QUARTER_LOCKED, message, 409)


def cross_reit(message="Child body references parents belonging to different REITs"):
    return ApiError(ERR_CROSS_REIT_REFERENCE, message, 422)


def invalid_date_range(message="Date range constraint violated"):
    return ApiError(ERR_INVALID_DATE_RANGE, message, 422)


def quarter_overlap(message="New quarter's closed interval intersects an existing quarter of the same reit"):
    return ApiError(ERR_QUARTER_OVERLAP, message, 409)


def reit_suspended(message="Operation not permitted while Reit.status == SUSPENDED"):
    return ApiError(ERR_REIT_SUSPENDED, message, 409)


def five_fifty_blocked(message="Dividend approve/declare blocked while Reit.five_fifty_blocked == true"):
    return ApiError(ERR_FIVE_FIFTY_BLOCKED, message, 409)


def segregation(message="Same X-User-ID attempted both sides of a segregated pairing"):
    return ApiError(ERR_SEGREGATION_OF_DUTIES, message, 403)


def requirement_not_posted(message="Dividend declare without a POSTED DistributionRequirement"):
    return ApiError(ERR_REQUIREMENT_NOT_POSTED, message, 409)


def declarations_open(message="Requirement close while sibling dividends remain in non-terminal states"):
    return ApiError(ERR_DECLARATIONS_OPEN, message, 409)


def stale_version(message="expected_reit_version does not match current Reit.version"):
    return ApiError(ERR_STALE_VERSION, message, 412)


def snapshot_empty(message="Finalize requested on a snapshot with zero positions"):
    return ApiError(ERR_SNAPSHOT_EMPTY, message, 422)
