"""Error catalog: error_id -> http status, plus ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def unauthenticated(msg="Missing or unrecognized authentication headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden_role(msg="Caller role is not authorized for this endpoint"):
    return ApiError("ERR_FORBIDDEN_ROLE", 403, msg)


def invalid_request(msg="Request body is malformed or missing required fields"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def invalid_enum(msg="Enum field carries an undeclared member"):
    return ApiError("ERR_INVALID_ENUM", 400, msg)


def not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def ownership(msg="Caller does not own the target resource"):
    return ApiError("ERR_OWNERSHIP_MISMATCH", 403, msg)


def invalid_state(msg="Entity is not in a state that allows this transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def appointment_terminal(msg="Appointment is in a terminal state"):
    return ApiError("ERR_APPOINTMENT_TERMINAL", 409, msg)


def alert_not_actionable(msg="Alert is not in an actionable state for this action"):
    return ApiError("ERR_ALERT_NOT_ACTIONABLE", 409, msg)


def subscription_not_active(msg="Subscription service_status is not ACTIVE"):
    return ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409, msg)


def dose_not_pending(msg="DoseEvent is not PENDING"):
    return ApiError("ERR_DOSE_NOT_PENDING", 409, msg)


def kit_not_delivered(msg="Kit is not in the required delivery state"):
    return ApiError("ERR_KIT_NOT_DELIVERED", 409, msg)


def stale_version(msg="Expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def safety_agent_required(msg="A MonitoringAgent is required for this action"):
    return ApiError("ERR_SAFETY_AGENT_REQUIRED", 403, msg)


def not_notified_contact(msg="Caller has no SENT notification for this alert"):
    return ApiError("ERR_NOT_NOTIFIED_CONTACT", 403, msg)


def device_safety_required(msg="Cannot decommission the last functional gateway of an actively monitored senior"):
    return ApiError("ERR_DEVICE_SAFETY_REQUIRED", 422, msg)


def window_too_short(msg="Install window duration outside [60, 240] minutes"):
    return ApiError("ERR_WINDOW_TOO_SHORT", 422, msg)


def rank_conflict(msg="priority_rank already used by an ACTIVE contact-tree entry of the senior"):
    return ApiError("ERR_RANK_CONFLICT", 409, msg)


def installer_conflict(msg="Window intersects installer's non-terminal appointment within the travel buffer"):
    return ApiError("ERR_INSTALLER_WINDOW_CONFLICT", 409, msg)


def senior_conflict(msg="Window overlaps a non-terminal appointment of the same senior"):
    return ApiError("ERR_SENIOR_WINDOW_CONFLICT", 409, msg)


def duplicate_report(msg="A FINAL wellness report already exists for an overlapping period"):
    return ApiError("ERR_DUPLICATE_REPORT", 409, msg)


def window_in_past(msg="window_start is not strictly after the current clock"):
    return ApiError("ERR_WINDOW_IN_PAST", 422, msg)


def outside_window(msg="Current clock is outside the appointment window"):
    return ApiError("ERR_OUTSIDE_APPOINTMENT_WINDOW", 409, msg)


def period_not_closed(msg="Report period is not temporally legal for the requested mode"):
    return ApiError("ERR_PERIOD_NOT_CLOSED", 422, msg)


def caregiver_senior_mismatch(msg="Caregiver serves a different senior"):
    return ApiError("ERR_CAREGIVER_SENIOR_MISMATCH", 422, msg)


def kit_senior_mismatch(msg="Kit belongs to a different senior"):
    return ApiError("ERR_KIT_SENIOR_MISMATCH", 422, msg)


def feature_gated(msg="Subscription plan does not include this feature"):
    return ApiError("ERR_FEATURE_GATED", 422, msg)


def contact_limit(msg="Senior's ACTIVE contact-tree entries reached the plan maximum"):
    return ApiError("ERR_CONTACT_LIMIT_EXCEEDED", 422, msg)


def billing_not_current(msg="Subscription billing_status is not CURRENT"):
    return ApiError("ERR_BILLING_NOT_CURRENT", 409, msg)
