"""Error classes and the error catalog (scaffold section 1.6 / PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def unauthenticated(msg="Missing or invalid X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def unauthorized(msg="Authenticated role is not permitted to call this endpoint"):
    return ApiError("ERR_UNAUTHORIZED", 403, msg)


def not_found(msg="Path id does not reference an existing row"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def reference_not_found(msg="Body foreign key references a missing row"):
    return ApiError("ERR_REFERENCE_NOT_FOUND", 422, msg)


def invalid_state(msg="Requested transition is not declared from the resource's current state"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def already_terminal(msg="Mutation attempted on a terminal-state resource"):
    return ApiError("ERR_ALREADY_TERMINAL", 409, msg)


def duty_segregation(msg="Segregation of duties violation"):
    return ApiError("ERR_DUTY_SEGREGATION", 422, msg)


def clinical_review_required(msg="Non-grievance case requires a DETERMINED clinical review before decision"):
    return ApiError("ERR_CLINICAL_REVIEW_REQUIRED", 422, msg)


def ack_window_missed(msg="Triage attempted more than 24h after received_at"):
    return ApiError("ERR_ACK_WINDOW_MISSED", 422, msg)


def ire_window_missed(msg="IRE referral attempted more than 72h after decided_at"):
    return ApiError("ERR_IRE_WINDOW_MISSED", 422, msg)


def reopen_window_missed(msg="Reopening requested outside its window"):
    return ApiError("ERR_REOPEN_WINDOW_MISSED", 422, msg)


def review_in_flight(msg="A live clinical review already exists for this case"):
    return ApiError("ERR_REVIEW_IN_FLIGHT", 409, msg)


def extension_consumed(msg="Extension already applied, or policy grants no extension hours"):
    return ApiError("ERR_EXTENSION_CONSUMED", 422, msg)


def expedited_not_allowed(msg="Expedited handling is not available for GRIEVANCE cases"):
    return ApiError("ERR_EXPEDITED_NOT_ALLOWED", 422, msg)


def policy_not_configured(msg="No active DeadlinePolicy for the case's (program, case_kind, priority_track)"):
    return ApiError("ERR_POLICY_NOT_CONFIGURED", 422, msg)


def notification_incomplete(msg="Notification completeness_score is below 1.00"):
    return ApiError("ERR_NOTIFICATION_INCOMPLETE", 422, msg)


def w9_required(msg="Payment effectuation requires Provider.w9_on_file"):
    return ApiError("ERR_W9_REQUIRED", 422, msg)


def waiver_not_allowed(msg="Only zero-amount effectuations may be waived"):
    return ApiError("ERR_WAIVER_NOT_ALLOWED", 422, msg)


def payment_not_allowed(msg="payment_amount_cents is negative or supplied with an UNFAVORABLE outcome"):
    return ApiError("ERR_PAYMENT_NOT_ALLOWED", 422, msg)


def duplicate_case(msg="A non-terminal duplicate case exists within the prior hour"):
    return ApiError("ERR_DUPLICATE_CASE", 409, msg)


def duplicate_snapshot(msg="Audit snapshot already captured this (report_period, case_id)"):
    return ApiError("ERR_DUPLICATE_SNAPSHOT", 409, msg)


def stale_version(msg="Expected version does not match the resource's current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def validation(msg="Malformed payload"):
    return ApiError("ERR_VALIDATION", 400, msg)
