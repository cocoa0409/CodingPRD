"""Error classes and error-id constants for the Campus Housing API."""


class ApiError(Exception):
    """An error carrying a machine-readable error_id and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (PRD §5).
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                        # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"            # 400
ERR_INVALID_DATE_RANGE = "ERR_INVALID_DATE_RANGE"      # 422
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_PRECONDITION_NOT_MET = "ERR_PRECONDITION_NOT_MET"  # 409
ERR_GENDER_INCOMPATIBLE = "ERR_GENDER_INCOMPATIBLE"    # 409
ERR_STUDENT_ON_HOLD = "ERR_STUDENT_ON_HOLD"            # 409
ERR_BREAK_OVERLAP = "ERR_BREAK_OVERLAP"                # 409
ERR_BREAK_CAPACITY_EXCEEDED = "ERR_BREAK_CAPACITY_EXCEEDED"  # 409
ERR_GROUP_SIZE_INVALID = "ERR_GROUP_SIZE_INVALID"      # 409
ERR_UNSETTLED_CHARGES = "ERR_UNSETTLED_CHARGES"        # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"               # 412
ERR_ROOM_OCCUPIED = "ERR_ROOM_OCCUPIED"               # 409
ERR_DUPLICATE_MEMBERSHIP = "ERR_DUPLICATE_MEMBERSHIP"  # 409
ERR_DUPLICATE_APPLICATION = "ERR_DUPLICATE_APPLICATION"  # 409
ERR_VALIDATION_PAGINATION = "ERR_VALIDATION_PAGINATION"  # 400


def unauthenticated(msg="Missing or unknown authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Caller is not permitted to perform this operation."):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Referenced resource does not exist."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Request body is malformed."):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def invalid_date_range(msg="check_out_date must be strictly after check_in_date."):
    return ApiError(ERR_INVALID_DATE_RANGE, 422, msg)


def invalid_state(msg="Resource is not in a valid state for this transition."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def precondition_not_met(msg="A cross-entity precondition failed."):
    return ApiError(ERR_PRECONDITION_NOT_MET, 409, msg)


def gender_incompatible(msg="Gender inclusivity incompatible with the room's occupants."):
    return ApiError(ERR_GENDER_INCOMPATIBLE, 409, msg)


def student_on_hold(msg="Student is on HOLD."):
    return ApiError(ERR_STUDENT_ON_HOLD, 409, msg)


def break_overlap(msg="Requested break interval overlaps an existing approved interval on the room."):
    return ApiError(ERR_BREAK_OVERLAP, 409, msg)


def break_capacity_exceeded(msg="Building break-housing capacity would be exceeded."):
    return ApiError(ERR_BREAK_CAPACITY_EXCEEDED, 409, msg)


def group_size_invalid(msg="Roommate group size precondition failed."):
    return ApiError(ERR_GROUP_SIZE_INVALID, 409, msg)


def unsettled_charges(msg="A damage charge on this assignment is still PENDING."):
    return ApiError(ERR_UNSETTLED_CHARGES, 409, msg)


def stale_version(msg="Supplied version does not match the current version."):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def room_occupied(msg="Room is occupied and cannot be taken offline."):
    return ApiError(ERR_ROOM_OCCUPIED, 409, msg)


def duplicate_membership(msg="Student already has an active membership in this group."):
    return ApiError(ERR_DUPLICATE_MEMBERSHIP, 409, msg)


def duplicate_application(msg="Student already has a non-terminal application in this cycle."):
    return ApiError(ERR_DUPLICATE_APPLICATION, 409, msg)


def validation_pagination(msg="limit must be 1..100 and offset must be >= 0."):
    return ApiError(ERR_VALIDATION_PAGINATION, 400, msg)
