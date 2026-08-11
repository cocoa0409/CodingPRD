"""Error classes carrying error_id, message, http_status per the scaffold catalog."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(message="Missing or invalid authentication headers"):
    return ApiError("ERR_UNAUTHENTICATED", message, 401)


def err_unauthorized(message="Role not permitted for this endpoint or ownership check failed"):
    return ApiError("ERR_UNAUTHORIZED", message, 403)


def err_not_found(message="Resource not found"):
    return ApiError("ERR_NOT_FOUND", message, 404)


def err_stale_version(message="expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", message, 412)


def err_invalid_request(message="Malformed body, missing required field, or invalid enum value"):
    return ApiError("ERR_INVALID_REQUEST", message, 400)


def err_invalid_state(message="Resource not in a valid from-state for the requested transition"):
    return ApiError("ERR_INVALID_STATE", message, 409)


def err_referential(message="Referenced entity missing, mismatched, or in a non-linkable state"):
    return ApiError("ERR_REFERENTIAL_INTEGRITY", message, 422)


def err_duplicate_child(message="Duplicate child resource for the same parent"):
    return ApiError("ERR_DUPLICATE_CHILD", message, 422)


def err_alumnus_not_lost(message="Linked AlumniRecord.status is not LOST"):
    return ApiError("ERR_ALUMNUS_NOT_LOST", message, 422)


def err_alumnus_not_active(message="AlumniRecord.status is not ACTIVE"):
    return ApiError("ERR_ALUMNUS_NOT_ACTIVE", message, 422)


def err_lead_confidence(message="lead_confidence below 60"):
    return ApiError("ERR_LEAD_CONFIDENCE_TOO_LOW", message, 422)


def err_reopen_limit(message="reopened_count would exceed 3"):
    return ApiError("ERR_CASE_REOPEN_LIMIT", message, 422)


def err_quorum(message="committee_count below committee_quorum_required"):
    return ApiError("ERR_QUORUM_NOT_MET", message, 422)


def err_no_active_tier(message="No ticket tier sales window covers the current logical clock"):
    return ApiError("ERR_NO_ACTIVE_TIER", message, 422)


def err_committee_locked(message="Committee is locked"):
    return ApiError("ERR_COMMITTEE_LOCKED", message, 422)


def err_chair_exists(message="An ACTIVE CHAIR membership already exists on this committee"):
    return ApiError("ERR_CHAIR_EXISTS", message, 422)


def err_event_not_open(message="Parent event status is not OPEN_FOR_REGISTRATION"):
    return ApiError("ERR_EVENT_NOT_OPEN", message, 422)


def err_event_held(message="Event already marked HELD"):
    return ApiError("ERR_EVENT_ALREADY_HELD", message, 422)


def err_tier_sold_out(message="Ticket tier is sold out"):
    return ApiError("ERR_TIER_SOLD_OUT", message, 422)


def err_sales_window_closed(message="Registration outside tier sales window"):
    return ApiError("ERR_SALES_WINDOW_CLOSED", message, 422)


def err_window_overlap(message="Tier sales window overlaps an existing tier of the same event"):
    return ApiError("ERR_WINDOW_OVERLAP", message, 422)


def err_venue_conflict(message="Program venue interval conflicts with another program of the same group"):
    return ApiError("ERR_VENUE_CONFLICT", message, 422)


def err_group_not_active(message="AffinityGroup.status is not ACTIVE"):
    return ApiError("ERR_GROUP_NOT_ACTIVE", message, 422)


def err_budget_exceeded(message="budget_allocated_cents exceeds group budget_remaining_cents"):
    return ApiError("ERR_BUDGET_EXCEEDED", message, 422)


def err_spend_overrun(message="actual_spend_cents exceeds budget_allocated_cents"):
    return ApiError("ERR_SPEND_OVERRUN", message, 422)


def err_programs_outstanding(message="Group has APPROVED or PUBLISHED programs"):
    return ApiError("ERR_PROGRAMS_OUTSTANDING", message, 422)


def err_channel_suppressed(message="Operation targets a suppressed (alumnus, channel)"):
    return ApiError("ERR_CHANNEL_SUPPRESSED", message, 422)


def err_not_milestone(message="Event milestone_year not positive and divisible by 5"):
    return ApiError("ERR_NOT_MILESTONE_YEAR", message, 422)


def err_campaign_not_active(message="Campaign status is not ACTIVE"):
    return ApiError("ERR_CAMPAIGN_NOT_ACTIVE", message, 422)


def err_campaign_not_closed(message="Campaign status is not CLOSED"):
    return ApiError("ERR_CAMPAIGN_NOT_CLOSED", message, 422)


def err_pledges_outstanding(message="Campaign has PLEDGED pledges"):
    return ApiError("ERR_PLEDGES_OUTSTANDING", message, 422)


def err_amount_too_small(message="Pledge amount_cents below 100"):
    return ApiError("ERR_AMOUNT_TOO_SMALL", message, 422)


def err_event_not_publishable(message="Linked event not in a publishable status"):
    return ApiError("ERR_EVENT_NOT_PUBLISHABLE", message, 422)
