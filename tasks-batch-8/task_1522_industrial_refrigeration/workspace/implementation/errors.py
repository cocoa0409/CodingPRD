"""Error catalogue (SCAFFOLD 1.6 / PRD 5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or _DEFAULT_MESSAGES.get(
            error_id, "The request could not be processed."
        )
        self.http_status = http_status or ERROR_HTTP[error_id]
        super().__init__(self.message)


ERROR_HTTP = {
    "ERR_VALIDATION": 400,
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_INVALID_WINDOW": 422,
    "ERR_PERMIT_WINDOW_CONFLICT": 409,
    "ERR_DRILL_GAP_VIOLATION": 409,
    "ERR_CONTRACTOR_NOT_QUALIFIED": 422,
    "ERR_EQUIPMENT_INTEGRITY_FAILED": 422,
    "ERR_FACILITY_NONCOMPLIANT": 409,
    "ERR_SYSTEM_OUT_OF_SERVICE": 409,
    "ERR_INVESTIGATOR_IS_REPORTER": 422,
    "ERR_VERIFIER_IS_COMPLETER": 422,
    "ERR_DRILL_TRAINING_SHORTFALL": 422,
    "ERR_ACTIONS_OPEN": 409,
    "ERR_CHARGE_NEGATIVE": 422,
    "ERR_QUANTITY_NOT_POSITIVE": 422,
    "ERR_CROSS_FACILITY_REFERENCE": 422,
    "ERR_NOTIFICATION_NOT_REQUIRED": 409,
    "ERR_PERMIT_OUTSIDE_WINDOW": 409,
    "ERR_SYSTEM_NOT_EMPTY": 409,
}

_DEFAULT_MESSAGES = {
    "ERR_VALIDATION": "The request failed schema or range validation.",
    "ERR_UNAUTHENTICATED": "X-User-Role / X-User-ID missing or the role is not recognized.",
    "ERR_FORBIDDEN": "The role is not permitted for this endpoint, or an identity pin failed.",
    "ERR_NOT_FOUND": "A referenced resource does not exist.",
    "ERR_STALE_VERSION": "The expected version does not match the current version.",
    "ERR_INVALID_STATE": "The resource is not in a valid source state for this transition.",
    "ERR_INVALID_WINDOW": "The declared time window is malformed or not in the future.",
    "ERR_PERMIT_WINDOW_CONFLICT": "The permit window overlaps another active permit on the same system.",
    "ERR_DRILL_GAP_VIOLATION": "The drill violates the 24h quiet gap against another drill of the facility.",
    "ERR_CONTRACTOR_NOT_QUALIFIED": "The contractor is not currently QUALIFIED.",
    "ERR_EQUIPMENT_INTEGRITY_FAILED": "An equipment on the system has integrity_status FAILED.",
    "ERR_FACILITY_NONCOMPLIANT": "The facility's compliance posture is NONCOMPLIANT.",
    "ERR_SYSTEM_OUT_OF_SERVICE": "The refrigeration system is not IN_SERVICE.",
    "ERR_INVESTIGATOR_IS_REPORTER": "The investigator must differ from the reporter.",
    "ERR_VERIFIER_IS_COMPLETER": "The incident investigator must differ from the action assignee.",
    "ERR_DRILL_TRAINING_SHORTFALL": "Fewer than 2 attendees hold non-expired AMMONIA_OPERATOR training.",
    "ERR_ACTIONS_OPEN": "The incident still has corrective actions that are not VERIFIED.",
    "ERR_CHARGE_NEGATIVE": "The REMOVE adjustment would drive the book inventory below zero.",
    "ERR_QUANTITY_NOT_POSITIVE": "The quantity must be strictly positive.",
    "ERR_CROSS_FACILITY_REFERENCE": "A referenced resource belongs to a different facility.",
    "ERR_NOTIFICATION_NOT_REQUIRED": "No regulatory notification is outstanding for this leak event.",
    "ERR_PERMIT_OUTSIDE_WINDOW": "The logical clock is outside the permit validity window.",
    "ERR_SYSTEM_NOT_EMPTY": "The system still carries a non-zero net book charge.",
}
