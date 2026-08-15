"""Error classes and error ID constants (from SCAFFOLD errors catalog)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_unauthorized(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED", msg, 403)


def err_not_found(msg="Path-templated resource does not exist"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_ref_not_found(msg="Body-referenced foreign key does not exist"):
    return ApiError("ERR_REFERENCED_NOT_FOUND", msg, 404)


def err_invalid_state(msg="State machine does not allow the transition from the current state"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_stale_version(msg="Expected version does not match the current version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def err_permit_required(msg="Minor role + minor talent but no VERIFIED permit covering the engagement span"):
    return ApiError("ERR_PERMIT_REQUIRED", msg, 422)


def err_minor_hours(msg="An engagement day exceeds the permit daily hour cap"):
    return ApiError("ERR_MINOR_HOURS_EXCEEDED", msg, 422)


def err_hold_talent_mismatch(msg="AvailabilityHold.talent_id differs from Submission.talent_id"):
    return ApiError("ERR_HOLD_TALENT_MISMATCH", msg, 422)


def err_slot_outside(msg="slot_start/slot_end not inside the session window"):
    return ApiError("ERR_SLOT_OUTSIDE_SESSION", msg, 422)


def err_talent_conflict(msg="Confirm would overlap an existing CONFIRMED appointment of the same talent"):
    return ApiError("ERR_TALENT_CONFLICT", msg, 409)


def err_session_full(msg="Session booked_count already equals capacity"):
    return ApiError("ERR_SESSION_FULL", msg, 409)


def err_invalid_window(msg="Hold window_start >= window_end or expires_at <= window_start"):
    return ApiError("ERR_INVALID_WINDOW", msg, 422)


def err_hold_outranked(msg="A higher-priority overlapping ACTIVE hold blocks this confirm"):
    return ApiError("ERR_HOLD_OUTRANKED", msg, 409)


def err_deadline_passed(msg="Submission attempted at/after breakdown.submission_deadline"):
    return ApiError("ERR_DEADLINE_PASSED", msg, 422)


def err_channel_forbidden(msg="AGENT_ONLY breakdown rejects self-submissions and non-franchised/inactive agents"):
    return ApiError("ERR_CHANNEL_FORBIDDEN", msg, 403)


def err_tape_too_long(msg="SelfTape.duration_seconds outside (0, 600]"):
    return ApiError("ERR_TAPE_TOO_LONG", msg, 422)


def err_invalid_offer_terms(msg="guarantee_cents out of bounds or not a multiple of 100"):
    return ApiError("ERR_INVALID_OFFER_TERMS", msg, 422)


def err_not_live_offer(msg="Action targets a non-live offer"):
    return ApiError("ERR_NOT_LIVE_OFFER", msg, 409)


def err_offer_expired(msg="Offer action attempted at/after offer.expires_at"):
    return ApiError("ERR_OFFER_EXPIRED", msg, 422)


def err_booking_precondition(msg="Booking lacks ACCEPTED offer / EXECUTED memo, or submission has a live booking"):
    return ApiError("ERR_BOOKING_PRECONDITION", msg, 422)


def err_engagement_overlap(msg="Another CONFIRMED booking for the same talent overlaps the engagement window"):
    return ApiError("ERR_ENGAGEMENT_OVERLAP", msg, 409)


def err_filing_window(msg="Taft-Hartley filing attempted in an impermissible state/window"):
    return ApiError("ERR_FILING_WINDOW", msg, 422)


def err_role_unfilled(msg="Production lock attempted while an OPEN role lacks a CONFIRMED booking"):
    return ApiError("ERR_ROLE_UNFILLED", msg, 422)


def err_invalid_request(msg="Required field missing or value out of domain"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)
