"""Error catalog (PRD §5 / scaffold §1.6).

Every error carries an error_id (machine-readable string), an HTTP status code,
and a human-readable message. The error_id and http_status values are taken
verbatim from the PRD error table.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error constructors (PRD §5 error catalogue) -----------------------------

def unauthenticated(msg="Missing or invalid authentication headers."):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden(msg="The acting role is not permitted to perform this operation."):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def not_found(msg="The referenced resource does not exist."):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_request(msg="The request body is malformed."):
    return ApiError("ERR_INVALID_REQUEST", 422, msg)


def invalid_state(msg="The resource is not in a valid state for this transition."):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def stale_room_version(msg="expected_room_version does not match the room's current version."):
    return ApiError("ERR_STALE_ROOM_VERSION", 412, msg)


def stale_reservation_version(msg="expected_reservation_version does not match the reservation's current version."):
    return ApiError("ERR_STALE_RESERVATION_VERSION", 412, msg)


def timing_window(msg="The request is outside the permitted timing window."):
    return ApiError("ERR_TIMING_WINDOW", 409, msg)


def capacity_exceeded(msg="party_size exceeds the room type capacity."):
    return ApiError("ERR_CAPACITY_EXCEEDED", 422, msg)


def room_type_mismatch(msg="Room/room-type/package mismatch."):
    return ApiError("ERR_ROOM_TYPE_MISMATCH", 422, msg)


def room_double_booked(msg="The requested interval overlaps an active reservation on this room."):
    return ApiError("ERR_ROOM_DOUBLE_BOOKED", 409, msg)


def extension_conflict(msg="The extension window overlaps a later active reservation on this room."):
    return ApiError("ERR_EXTENSION_CONFLICT", 409, msg)


def room_not_available(msg="The room must be AVAILABLE to be taken out of service."):
    return ApiError("ERR_ROOM_NOT_AVAILABLE", 409, msg)


def not_queue_head(msg="Only the head-of-queue entry may be played."):
    return ApiError("ERR_NOT_QUEUE_HEAD", 409, msg)


def validation(msg="A field-level validation error occurred."):
    return ApiError("ERR_VALIDATION", 422, msg)
