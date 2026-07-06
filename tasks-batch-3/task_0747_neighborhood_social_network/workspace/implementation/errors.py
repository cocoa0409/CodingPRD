"""Domain error classes; mapped to standard error envelope at the Flask boundary."""
from __future__ import annotations


class ApiError(Exception):
    error_id: str = "ERR_INVALID_REQUEST"
    http_status: int = 400

    def __init__(self, message: str = "", error_id: str | None = None, http_status: int | None = None):
        super().__init__(message or self.error_id)
        self.message = message or self.error_id
        if error_id is not None:
            self.error_id = error_id
        if http_status is not None:
            self.http_status = http_status


class Unauthenticated(ApiError):
    error_id = "ERR_UNAUTHENTICATED"
    http_status = 401


class Forbidden(ApiError):
    error_id = "ERR_FORBIDDEN"
    http_status = 403


class NotFound(ApiError):
    error_id = "ERR_NOT_FOUND"
    http_status = 404


class ReferenceNotFound(ApiError):
    error_id = "ERR_REFERENCE_NOT_FOUND"
    http_status = 404


class InvalidRequest(ApiError):
    error_id = "ERR_INVALID_REQUEST"
    http_status = 400


class InvalidState(ApiError):
    error_id = "ERR_INVALID_STATE"
    http_status = 409


class StaleTargetVersion(ApiError):
    error_id = "ERR_STALE_TARGET_VERSION"
    http_status = 412


class ResidentSuspended(ApiError):
    error_id = "ERR_RESIDENT_SUSPENDED"
    http_status = 403


class NotVerifiedInNeighborhood(ApiError):
    error_id = "ERR_NOT_VERIFIED_IN_NEIGHBORHOOD"
    http_status = 403


class NeighborhoodEmergencyLockdown(ApiError):
    error_id = "ERR_NEIGHBORHOOD_EMERGENCY_LOCKDOWN"
    http_status = 409


class InvalidTimeWindow(ApiError):
    error_id = "ERR_INVALID_TIME_WINDOW"
    http_status = 422


class EffectiveFromInPast(ApiError):
    error_id = "ERR_EFFECTIVE_FROM_IN_PAST"
    http_status = 422


class NoticeWindowOverlap(ApiError):
    error_id = "ERR_NOTICE_WINDOW_OVERLAP"
    http_status = 409


class GroupEventCapacity(ApiError):
    error_id = "ERR_GROUP_EVENT_CAPACITY"
    http_status = 409


class NotOwner(ApiError):
    error_id = "ERR_NOT_OWNER"
    http_status = 403


class LocationOutsideGeofence(ApiError):
    error_id = "ERR_LOCATION_OUTSIDE_GEOFENCE"
    http_status = 422


class InvalidBudget(ApiError):
    error_id = "ERR_INVALID_BUDGET"
    http_status = 422


class InvalidPrice(ApiError):
    error_id = "ERR_INVALID_PRICE"
    http_status = 422


class DuplicateFlag(ApiError):
    error_id = "ERR_DUPLICATE_FLAG"
    http_status = 409


class CannotReserveOwn(ApiError):
    error_id = "ERR_CANNOT_RESERVE_OWN"
    http_status = 409


class EventFull(ApiError):
    error_id = "ERR_EVENT_FULL"
    http_status = 409


class AdExhausted(ApiError):
    error_id = "ERR_AD_EXHAUSTED"
    http_status = 409
