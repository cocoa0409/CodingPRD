"""Error catalog from PRD §5 (the canonical (error_id, HTTP-status) table).

The `ERROR_CATALOG` dict is the single source of truth — when a handler
raises an `ApiError(error_id, message)`, the http_status is looked up here
unless explicitly overridden.
"""
from __future__ import annotations

from typing import Dict

# (error_id → http_status) verbatim from PRD §5.
ERROR_CATALOG: Dict[str, int] = {
    # Auth.
    "ERR_MISSING_USER_CONTEXT_HEADER": 400,
    "ERR_UNKNOWN_ROLE": 403,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    "ERR_AUDIT_LOG_FORBIDDEN": 403,
    # Not-found family.
    "ERR_FESTIVAL_NOT_FOUND": 404,
    "ERR_PROGRAM_VERSION_NOT_FOUND": 404,
    "ERR_STAGE_NOT_FOUND": 404,
    "ERR_EQUIPMENT_KIT_NOT_FOUND": 404,
    "ERR_ARTIST_NOT_FOUND": 404,
    "ERR_PROGRAM_ITEM_NOT_FOUND": 404,
    "ERR_RIDER_NOT_FOUND": 404,
    "ERR_SOUND_ENGINEER_TEAM_NOT_FOUND": 404,
    "ERR_SOUND_CHECK_NOT_FOUND": 404,
    "ERR_REHEARSAL_NOT_FOUND": 404,
    "ERR_TICKET_TYPE_NOT_FOUND": 404,
    "ERR_SPONSOR_TIER_NOT_FOUND": 404,
    "ERR_EXPOSURE_ALLOCATION_NOT_FOUND": 404,
    "ERR_SCHEDULE_CHANGE_NOT_FOUND": 404,
    "ERR_RESOURCE_MISMATCHED_PARENT": 404,
    # Body shape.
    "ERR_INVALID_REQUEST_BODY": 400,
    "ERR_INVALID_FIELD_VALUE": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_INVALID_FESTIVAL_WINDOW": 400,
    # Festival state.
    "ERR_FESTIVAL_NOT_SCHEDULING_OR_PUBLISHED": 409,
    "ERR_FESTIVAL_NOT_PUBLISHED": 409,
    "ERR_FESTIVAL_ALREADY_CLOSED": 409,
    # Program version.
    "ERR_PROGRAM_VERSION_SUPERSEDED": 409,
    "ERR_EMPTY_PROGRAM_VERSION": 409,
    "ERR_MISSING_REVISION_REASON": 400,
    "ERR_MISSING_REJECTION_REASON": 400,
    "ERR_MISSING_VOID_REASON": 400,
    # Program item state.
    "ERR_PROGRAM_ITEM_NOT_PROPOSED": 409,
    "ERR_PROGRAM_ITEM_NOT_CONFIRMED": 409,
    "ERR_PROGRAM_ITEM_NOT_MUTABLE": 409,
    "ERR_PROGRAM_ITEM_ALREADY_CANCELLED": 409,
    "ERR_PROGRAM_ITEM_NOT_TERMINAL_FOR_PERFORM": 409,
    "ERR_PARENT_ITEM_NOT_READY": 409,
    # Team and sound-check.
    "ERR_TEAM_NOT_AVAILABLE": 409,
    "ERR_TEAM_HAS_ACTIVE_SLOT": 409,
    "ERR_SOUND_CHECK_NOT_SCHEDULED": 409,
    "ERR_SOUND_CHECK_NOT_TERMINAL": 409,
    "ERR_SOUND_CHECK_STAGE_MISMATCH": 409,
    "ERR_SOUND_CHECK_WINDOW_INVALID": 422,
    "ERR_ENGINEER_TEAM_DOUBLE_BOOKED": 409,
    # Rehearsal.
    "ERR_REHEARSAL_NOT_BOOKED": 409,
    "ERR_REHEARSAL_ROOM_OVERLAP": 409,
    # Ticket.
    "ERR_TICKET_TYPE_NOT_ACTIVE": 409,
    "ERR_TICKET_TYPE_TIE_INVALID": 409,
    "ERR_TICKET_ZONE_CAPACITY_EXCEEDED": 422,
    "ERR_TICKET_ZONE_NO_STAGE": 422,
    "ERR_REFUND_EXCEEDS_PROVISIONAL": 422,
    "ERR_CROSS_FESTIVAL_REFUND": 422,
    # Schedule change.
    "ERR_CHANGE_NOT_PROPOSED": 409,
    "ERR_CHANGE_NOT_APPLIED": 409,
    "ERR_CHANGE_ALREADY_ACKED": 409,
    "ERR_SYNC_ENVELOPE_NOT_QUEUED": 409,
    "ERR_SYNC_TARGET_UNKNOWN": 400,
    # Equipment / stage / interval.
    "ERR_STAGE_LACKS_EQUIPMENT_KIT": 409,
    "ERR_EQUIPMENT_KIT_OVERSUBSCRIBED": 409,
    "ERR_STAGE_CHANGEOVER_OVERLAP": 409,
    "ERR_ARTIST_TRAVEL_BUFFER_VIOLATION": 409,
    "ERR_ARTIST_MULTI_FESTIVAL_CONFLICT": 409,
    "ERR_ARTIST_SELF_OVERLAP": 409,
    "ERR_CHILD_WINDOW_OUT_OF_FESTIVAL_RANGE": 422,
    # Headliner / rider.
    "ERR_HEADLINER_MISSING_BLOCKING_RIDER": 422,
    "ERR_BLOCKING_RIDERS_UNFULFILLED": 422,
    # Sponsor / exposure.
    "ERR_EXPOSURE_KIND_NOT_CONTRACTED": 422,
    "ERR_ARTIST_NOT_ELIGIBLE_FOR_TIER": 422,
    "ERR_EXPOSURE_PROGRAM_ITEM_CROSS_FESTIVAL": 422,
    "ERR_TIER_CONTRACT_UNITS_EXCEEDED": 422,
    "ERR_EXPOSURE_CATALOG_BELOW_DISBURSED": 422,
    "ERR_EXPOSURE_ALLOCATION_NOT_DELIVERABLE": 409,
    "ERR_EXPOSURE_ALLOCATION_TERMINAL": 409,
    "ERR_TIER_POOL_EXHAUSTED": 409,
    "ERR_TIER_POOL_RACE": 409,
    "ERR_CONCURRENT_SWEEP_IN_PROGRESS": 409,
    # OCC / idempotency.
    "ERR_VERSION_CONFLICT": 409,
    "ERR_IDEMPOTENCY_KEY_REUSED": 409,
    # Operator surface.
    "ERR_CLOCK_ADVANCE_BACKWARD": 400,
    "ERR_CLOCK_INVALID_ARGS": 400,
    "ERR_SWEEP_FESTIVAL_NOT_FOUND": 404,
    # Misc team-state.
    "ERR_TEAM_NOT_AVAILABLE_ALIAS": 409,  # placeholder for forward-compat
}


class ApiError(Exception):
    """The single exception type the route handlers throw.

    The before-request hook and the per-blueprint handlers catch this and
    materialise the standard error envelope.
    """

    def __init__(
        self,
        error_id: str,
        message: str = "",
        http_status: int | None = None,
    ) -> None:
        super().__init__(message or error_id)
        if error_id not in ERROR_CATALOG and http_status is None:
            # Unknown id without an explicit status defaults to 400 — keeps
            # the envelope writable even on a programmer slip.
            http_status = 400
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = (
            http_status if http_status is not None else ERROR_CATALOG.get(error_id, 400)
        )


def lookup_status(error_id: str) -> int:
    """Return the canonical HTTP status for an error_id, falling back to 400."""
    return ERROR_CATALOG.get(error_id, 400)
