"""Error catalogue (PRD section 5 / SCAFFOLD section 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


# error_id -> http status
CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_CROSS_TENANT_ACCESS": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CONTACT_OPTED_OUT": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_BUSINESS_NOT_FOUND": 404,
    "ERR_LOCATION_NOT_FOUND": 404,
    "ERR_LISTING_NOT_FOUND": 404,
    "ERR_CONTACT_NOT_FOUND": 404,
    "ERR_TEMPLATE_NOT_FOUND": 404,
    "ERR_CAMPAIGN_NOT_FOUND": 404,
    "ERR_REQUEST_NOT_FOUND": 404,
    "ERR_REVIEW_NOT_FOUND": 404,
    "ERR_RESPONSE_NOT_FOUND": 404,
    "ERR_ESCALATION_NOT_FOUND": 404,
    "ERR_SURVEY_NOT_FOUND": 404,
    "ERR_WIDGET_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_LOCATION_FROZEN": 409,
    "ERR_LOCATION_RESTRICTED": 409,
    "ERR_SURVEY_EXPIRED": 409,
    "ERR_LISTING_NOT_CONNECTED": 409,
    "ERR_REVIEW_NOT_RESPONDED": 409,
    "ERR_TEMPLATE_RATING_MISMATCH": 422,
    "ERR_DUPLICATE_LISTING": 409,
    "ERR_DUPLICATE_EXTERNAL_REVIEW": 409,
    "ERR_WIDGET_ALREADY_EXISTS": 409,
    "ERR_SEND_WINDOW_CONFLICT": 409,
    "ERR_FREQUENCY_CAP_ACTIVE": 409,
    "ERR_INSUFFICIENT_CREDITS": 402,
    "ERR_SEND_CAP_EXCEEDED": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or the role is not recognised.",
    "ERR_UNAUTHORIZED": "The acting role is not authorized for this endpoint.",
    "ERR_CROSS_TENANT_ACCESS": "The acting identity does not own the target resource.",
    "ERR_SEGREGATION_OF_DUTIES": "The drafter of a response may not approve or reject it.",
    "ERR_CONTACT_OPTED_OUT": "The contact has opted out or lacks consent for this channel.",
    "ERR_INVALID_REQUEST": "The request body or query string is malformed.",
    "ERR_BUSINESS_NOT_FOUND": "Business not found.",
    "ERR_LOCATION_NOT_FOUND": "Location not found.",
    "ERR_LISTING_NOT_FOUND": "Listing not found.",
    "ERR_CONTACT_NOT_FOUND": "Contact not found.",
    "ERR_TEMPLATE_NOT_FOUND": "Response template not found.",
    "ERR_CAMPAIGN_NOT_FOUND": "Campaign not found.",
    "ERR_REQUEST_NOT_FOUND": "Review request not found.",
    "ERR_REVIEW_NOT_FOUND": "Review not found.",
    "ERR_RESPONSE_NOT_FOUND": "Review response not found.",
    "ERR_ESCALATION_NOT_FOUND": "Escalation not found.",
    "ERR_SURVEY_NOT_FOUND": "Survey not found.",
    "ERR_WIDGET_NOT_FOUND": "Widget not found.",
    "ERR_STALE_VERSION": "The supplied version does not match the current version.",
    "ERR_INVALID_STATE": "The requested transition is not legal from the current state.",
    "ERR_LOCATION_FROZEN": "The location is FROZEN by a compliance hold.",
    "ERR_LOCATION_RESTRICTED": "The location's posture is RESTRICTED.",
    "ERR_SURVEY_EXPIRED": "The survey has expired.",
    "ERR_LISTING_NOT_CONNECTED": "No CONNECTED listing exists for the review's site.",
    "ERR_REVIEW_NOT_RESPONDED": "The underlying review has not been responded to.",
    "ERR_TEMPLATE_RATING_MISMATCH": "The template's rating band does not contain the review's rating.",
    "ERR_DUPLICATE_LISTING": "A listing already exists for this location and site.",
    "ERR_DUPLICATE_EXTERNAL_REVIEW": "A review already exists for this location, site and external id.",
    "ERR_WIDGET_ALREADY_EXISTS": "The location already has a widget.",
    "ERR_SEND_WINDOW_CONFLICT": "The buffered send window collides with another campaign.",
    "ERR_FREQUENCY_CAP_ACTIVE": "The contact is still inside its frequency-cap cooldown.",
    "ERR_INSUFFICIENT_CREDITS": "The campaign has no credits available.",
    "ERR_SEND_CAP_EXCEEDED": "The batch would exceed the campaign's daily send cap.",
}


def err(error_id, message=None):
    return ApiError(error_id, CATALOG[error_id], message)
