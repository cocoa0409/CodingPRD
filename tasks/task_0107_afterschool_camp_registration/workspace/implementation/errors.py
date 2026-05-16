"""Error catalog for the Afterschool Camp Registration API.

Error IDs and HTTP statuses come straight from SCAFFOLD §1.6 / PRD §5.
"""

ERROR_HTTP_STATUS = {
    "ERR_AUTH_REQUIRED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_FAMILY_MISMATCH": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_TIME_RANGE": 422,
    "ERR_INVALID_WEEK_INDEX": 422,
    "ERR_AGE_OUT_OF_RANGE": 422,
    "ERR_MEDICAL_AUTH_REQUIRED": 422,
    "ERR_PICKUP_AUTH_REQUIRED": 422,
    "ERR_EMERGENCY_CONTACT_REQUIRED": 422,
    "ERR_AUTHORIZATION_NOT_ACTIVE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_DUPLICATE_ENROLLMENT": 409,
    "ERR_WEEKLY_CAPACITY_FULL": 409,
    "ERR_SCHOLARSHIP_INELIGIBLE": 422,
    "ERR_SCHOLARSHIP_EXHAUSTED": 409,
    "ERR_EMERGENCY_CONTACT_PRIORITY_TAKEN": 409,
    "ERR_RAINY_POOL_EXHAUSTED": 422,
    "ERR_STALE_VERSION": 409,
    "ERR_FAMILY_HAS_FUTURE_ENROLLMENTS": 409,
}


_DEFAULT_MESSAGES = {
    "ERR_AUTH_REQUIRED": "Authentication headers missing or invalid.",
    "ERR_FORBIDDEN": "Role lacks permission for this endpoint.",
    "ERR_FAMILY_MISMATCH": "Guardian may only act on resources in their own family.",
    "ERR_RESOURCE_NOT_FOUND": "Resource not found.",
    "ERR_VALIDATION": "Request body is malformed.",
    "ERR_INVALID_TIME_RANGE": "expires_at must be strictly greater than effective_at.",
    "ERR_INVALID_WEEK_INDEX": "week_index out of range or session-day weather change on past date.",
    "ERR_AGE_OUT_OF_RANGE": "Child's age on the session's reference_date is outside the session's age window.",
    "ERR_MEDICAL_AUTH_REQUIRED": "Confirmation requires an ACTIVE MEDICAL authorization.",
    "ERR_PICKUP_AUTH_REQUIRED": "Confirmation requires an ACTIVE PICKUP authorization.",
    "ERR_EMERGENCY_CONTACT_REQUIRED": "Confirmation requires at least one emergency contact.",
    "ERR_AUTHORIZATION_NOT_ACTIVE": "Operation requires an ACTIVE Authorization.",
    "ERR_INVALID_STATE": "Operation is not legal in current state.",
    "ERR_DUPLICATE_ENROLLMENT": "A non-terminal enrollment already exists for (child_id, session_id, week_index).",
    "ERR_WEEKLY_CAPACITY_FULL": "Weekly capacity reached during concurrent confirmation.",
    "ERR_SCHOLARSHIP_INELIGIBLE": "Scholarship award is not ACTIVE or incompatible with session kind.",
    "ERR_SCHOLARSHIP_EXHAUSTED": "Scholarship award credit pool would overflow.",
    "ERR_EMERGENCY_CONTACT_PRIORITY_TAKEN": "Another non-archived emergency contact already has this priority.",
    "ERR_RAINY_POOL_EXHAUSTED": "Rainy-day pool is insufficient to cover confirmed attendees for the day.",
    "ERR_STALE_VERSION": "Supplied version does not match the current persisted version.",
    "ERR_FAMILY_HAS_FUTURE_ENROLLMENTS": "Family has CONFIRMED enrollments for future weeks.",
}


class APIError(Exception):
    """Domain exception carrying error_id, message, and http_status."""

    def __init__(self, error_id, message=None):
        if error_id not in ERROR_HTTP_STATUS:
            raise ValueError(f"Unknown error_id: {error_id}")
        self.error_id = error_id
        self.http_status = ERROR_HTTP_STATUS[error_id]
        self.message = message or _DEFAULT_MESSAGES.get(error_id, "Error.")
        super().__init__(self.message)
