"""Error identifier constants and the error id -> HTTP status registry.

The PRD publishes a fixed catalogue of error identifiers, each bound to exactly
one HTTP status. Registering that mapping with the framework lets
``validate_error(response, ERR_X)`` cross-check the transport status without
each test restating it.
"""

from prd_bench_local_runner.testing.validators import set_error_http_status_map


# --------------------------------------------------------------------------
# Authentication and authorisation
# --------------------------------------------------------------------------

ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_ROLE_NOT_PERMITTED = "ERR_ROLE_NOT_PERMITTED"
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"


# --------------------------------------------------------------------------
# Existence
# --------------------------------------------------------------------------

ERR_CAMPAIGN_NOT_FOUND = "ERR_CAMPAIGN_NOT_FOUND"
ERR_MILESTONE_NOT_FOUND = "ERR_MILESTONE_NOT_FOUND"
ERR_LEGISLATOR_NOT_FOUND = "ERR_LEGISLATOR_NOT_FOUND"
ERR_SUPPORTER_NOT_FOUND = "ERR_SUPPORTER_NOT_FOUND"
ERR_SEGMENT_NOT_FOUND = "ERR_SEGMENT_NOT_FOUND"
ERR_VARIANT_NOT_FOUND = "ERR_VARIANT_NOT_FOUND"
ERR_PARTNER_NOT_FOUND = "ERR_PARTNER_NOT_FOUND"
ERR_ENDORSEMENT_NOT_FOUND = "ERR_ENDORSEMENT_NOT_FOUND"
ERR_ACTIVATION_NOT_FOUND = "ERR_ACTIVATION_NOT_FOUND"
ERR_ACTION_RECORD_NOT_FOUND = "ERR_ACTION_RECORD_NOT_FOUND"
ERR_SPOKESPERSON_NOT_FOUND = "ERR_SPOKESPERSON_NOT_FOUND"
ERR_MEETING_NOT_FOUND = "ERR_MEETING_NOT_FOUND"


# --------------------------------------------------------------------------
# Request shape
# --------------------------------------------------------------------------

ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"


# --------------------------------------------------------------------------
# Optimistic concurrency
# --------------------------------------------------------------------------

ERR_STALE_SEGMENT_VERSION = "ERR_STALE_SEGMENT_VERSION"
ERR_STALE_VARIANT_VERSION = "ERR_STALE_VARIANT_VERSION"


# --------------------------------------------------------------------------
# Campaign lifecycle and posture
# --------------------------------------------------------------------------

ERR_CAMPAIGN_NOT_ACTIVE = "ERR_CAMPAIGN_NOT_ACTIVE"
ERR_CAMPAIGN_FROZEN = "ERR_CAMPAIGN_FROZEN"
ERR_CAMPAIGN_RESTRICTED = "ERR_CAMPAIGN_RESTRICTED"
ERR_INVALID_STATE_TRANSITION = "ERR_INVALID_STATE_TRANSITION"
ERR_NO_TARGET_LEGISLATOR = "ERR_NO_TARGET_LEGISLATOR"
ERR_ACTIVATION_IN_FLIGHT = "ERR_ACTIVATION_IN_FLIGHT"
ERR_OUTSIDE_SEND_WINDOW = "ERR_OUTSIDE_SEND_WINDOW"


# --------------------------------------------------------------------------
# Consent and lawful basis
# --------------------------------------------------------------------------

ERR_CONSENT_MISSING = "ERR_CONSENT_MISSING"
ERR_SUPPORTER_SUPPRESSED = "ERR_SUPPORTER_SUPPRESSED"
ERR_LAWFUL_BASIS_INVALID = "ERR_LAWFUL_BASIS_INVALID"
ERR_STORY_CONSENT_REQUIRED = "ERR_STORY_CONSENT_REQUIRED"


# --------------------------------------------------------------------------
# Temporal windows
# --------------------------------------------------------------------------

ERR_INVALID_WINDOW = "ERR_INVALID_WINDOW"
ERR_WINDOW_OUTSIDE_CAMPAIGN = "ERR_WINDOW_OUTSIDE_CAMPAIGN"
ERR_BLACKOUT_WINDOW = "ERR_BLACKOUT_WINDOW"
ERR_MEETING_WINDOW_CONFLICT = "ERR_MEETING_WINDOW_CONFLICT"
ERR_CHANNEL_WINDOW_SATURATED = "ERR_CHANNEL_WINDOW_SATURATED"


# --------------------------------------------------------------------------
# Uniqueness
# --------------------------------------------------------------------------

ERR_DUPLICATE_ENDORSEMENT = "ERR_DUPLICATE_ENDORSEMENT"
ERR_DUPLICATE_SPOKESPERSON = "ERR_DUPLICATE_SPOKESPERSON"


# --------------------------------------------------------------------------
# Collaborator readiness
# --------------------------------------------------------------------------

ERR_PARTNER_WITHDRAWN = "ERR_PARTNER_WITHDRAWN"
ERR_REVISION_LIMIT_REACHED = "ERR_REVISION_LIMIT_REACHED"
ERR_NO_ELIGIBLE_VARIANT = "ERR_NO_ELIGIBLE_VARIANT"
ERR_VARIANT_NOT_LOCKED = "ERR_VARIANT_NOT_LOCKED"
ERR_SPOKESPERSON_NOT_CERTIFIED = "ERR_SPOKESPERSON_NOT_CERTIFIED"
ERR_ENDORSEMENT_QUORUM_NOT_MET = "ERR_ENDORSEMENT_QUORUM_NOT_MET"


# --------------------------------------------------------------------------
# Scope agreement
# --------------------------------------------------------------------------

ERR_CAMPAIGN_MISMATCH = "ERR_CAMPAIGN_MISMATCH"
ERR_CHANNEL_NOT_IN_VARIANT_SCOPE = "ERR_CHANNEL_NOT_IN_VARIANT_SCOPE"
ERR_DISTRICT_MISMATCH = "ERR_DISTRICT_MISMATCH"


# --------------------------------------------------------------------------
# Capacity and fiscal
# --------------------------------------------------------------------------

ERR_SEGMENT_EMPTY = "ERR_SEGMENT_EMPTY"
ERR_FREQUENCY_CAP_EXHAUSTED = "ERR_FREQUENCY_CAP_EXHAUSTED"
ERR_REACH_BELOW_MINIMUM = "ERR_REACH_BELOW_MINIMUM"
ERR_DELIVERY_TALLY_MISMATCH = "ERR_DELIVERY_TALLY_MISMATCH"


ERROR_HTTP_STATUS = {
    # 401
    ERR_UNAUTHENTICATED: 401,
    # 403
    ERR_ROLE_NOT_PERMITTED: 403,
    ERR_NOT_RESOURCE_OWNER: 403,
    ERR_SEGREGATION_OF_DUTIES: 403,
    # 404
    ERR_CAMPAIGN_NOT_FOUND: 404,
    ERR_MILESTONE_NOT_FOUND: 404,
    ERR_LEGISLATOR_NOT_FOUND: 404,
    ERR_SUPPORTER_NOT_FOUND: 404,
    ERR_SEGMENT_NOT_FOUND: 404,
    ERR_VARIANT_NOT_FOUND: 404,
    ERR_PARTNER_NOT_FOUND: 404,
    ERR_ENDORSEMENT_NOT_FOUND: 404,
    ERR_ACTIVATION_NOT_FOUND: 404,
    ERR_ACTION_RECORD_NOT_FOUND: 404,
    ERR_SPOKESPERSON_NOT_FOUND: 404,
    ERR_MEETING_NOT_FOUND: 404,
    # 409
    ERR_CAMPAIGN_NOT_ACTIVE: 409,
    ERR_CAMPAIGN_FROZEN: 409,
    ERR_CAMPAIGN_RESTRICTED: 409,
    ERR_INVALID_STATE_TRANSITION: 409,
    ERR_NO_TARGET_LEGISLATOR: 409,
    ERR_ACTIVATION_IN_FLIGHT: 409,
    ERR_OUTSIDE_SEND_WINDOW: 409,
    ERR_PARTNER_WITHDRAWN: 409,
    ERR_REVISION_LIMIT_REACHED: 409,
    ERR_NO_ELIGIBLE_VARIANT: 409,
    ERR_BLACKOUT_WINDOW: 409,
    ERR_MEETING_WINDOW_CONFLICT: 409,
    ERR_CHANNEL_WINDOW_SATURATED: 409,
    ERR_DUPLICATE_ENDORSEMENT: 409,
    ERR_DUPLICATE_SPOKESPERSON: 409,
    ERR_VARIANT_NOT_LOCKED: 409,
    ERR_SPOKESPERSON_NOT_CERTIFIED: 409,
    ERR_ENDORSEMENT_QUORUM_NOT_MET: 409,
    ERR_SEGMENT_EMPTY: 409,
    ERR_FREQUENCY_CAP_EXHAUSTED: 409,
    ERR_REACH_BELOW_MINIMUM: 409,
    ERR_DELIVERY_TALLY_MISMATCH: 409,
    # 412
    ERR_STALE_SEGMENT_VERSION: 412,
    ERR_STALE_VARIANT_VERSION: 412,
    # 422
    ERR_INVALID_REQUEST: 422,
    ERR_CONSENT_MISSING: 422,
    ERR_SUPPORTER_SUPPRESSED: 422,
    ERR_LAWFUL_BASIS_INVALID: 422,
    ERR_STORY_CONSENT_REQUIRED: 422,
    ERR_INVALID_WINDOW: 422,
    ERR_WINDOW_OUTSIDE_CAMPAIGN: 422,
    ERR_CAMPAIGN_MISMATCH: 422,
    ERR_CHANNEL_NOT_IN_VARIANT_SCOPE: 422,
    ERR_DISTRICT_MISMATCH: 422,
}

# Register once at import time so validate_error() can infer the status.
set_error_http_status_map(ERROR_HTTP_STATUS)
