"""Error catalog and the ApiError exception (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or ERROR_MESSAGE.get(error_id, error_id)
        super().__init__(self.message)


# error_id -> (http_status, default message)
_CATALOG = [
    ("ERR_MISSING_AUTH_HEADERS", 401, "Both X-User-ID and X-User-Role headers are required."),
    ("ERR_INVALID_ROLE", 401, "X-User-Role is not one of the five recognised roles."),
    ("ERR_UNAUTHORIZED", 403, "This role may not perform this operation."),
    ("ERR_ACTOR_NOT_FOUND", 403, "X-User-ID does not resolve to a row of the backing entity."),
    ("ERR_NOT_CHIEF_PERFUSIONIST", 403, "Caller acting as ChiefPerfusionist is not flagged is_chief."),
    ("ERR_INVALID_REQUEST", 400, "A required field is missing or null."),
    ("ERR_INVALID_FIELD_VALUE", 422, "A supplied field violates its type, enum, range or precision constraint."),
    ("ERR_INVALID_PAGINATION", 400, "limit or offset is outside the permitted range."),
    ("ERR_CONTRACT_NOT_FOUND", 404, "Hospital contract not found."),
    ("ERR_SURGEON_NOT_FOUND", 404, "Surgeon not found."),
    ("ERR_PREFERENCE_CARD_NOT_FOUND", 404, "Preference card not found."),
    ("ERR_PERFUSIONIST_NOT_FOUND", 404, "Perfusionist not found."),
    ("ERR_CE_ACTIVITY_NOT_FOUND", 404, "Continuing-education activity not found."),
    ("ERR_DEVICE_NOT_FOUND", 404, "Perfusion device not found."),
    ("ERR_ROTATION_SLOT_NOT_FOUND", 404, "Call rotation slot not found."),
    ("ERR_CASE_NOT_FOUND", 404, "Bypass case not found."),
    ("ERR_PACK_NOT_FOUND", 404, "Disposable pack not found."),
    ("ERR_CHECKLIST_NOT_FOUND", 404, "Pump checklist not found."),
    ("ERR_ECMO_RUN_NOT_FOUND", 404, "ECMO run not found."),
    ("ERR_INCIDENT_NOT_FOUND", 404, "Incident report not found."),
    ("ERR_NOT_CARD_OWNER", 403, "A surgeon may only act on their own preference cards."),
    ("ERR_NOT_ASSIGNED_PERFUSIONIST", 403, "Caller is not the perfusionist assigned to this work."),
    ("ERR_SEGREGATION_OF_DUTIES", 403, "The same perfusionist may not both file and adjudicate this report."),
    ("ERR_STALE_CASE_VERSION", 412, "expected_case_version does not match the stored case version."),
    ("ERR_STALE_CONTRACT_VERSION", 412, "expected_contract_version does not match the stored contract version."),
    ("ERR_CASE_NOT_ASSIGNABLE", 409, "Case is not in a state that accepts a staffing assignment."),
    ("ERR_CASE_NOT_STAFFED", 409, "Case is not in STAFFED."),
    ("ERR_CASE_NOT_PACK_CONFIGURED", 409, "Case is not in PACK_CONFIGURED."),
    ("ERR_CHECKLIST_NOT_DRAFT", 409, "Checklist is not in DRAFT."),
    ("ERR_CASE_NOT_SETUP_VERIFIED", 409, "Case is not in SETUP_VERIFIED."),
    ("ERR_CASE_NOT_ON_BYPASS", 409, "Case is not in ON_BYPASS."),
    ("ERR_CASE_NOT_OFF_BYPASS", 409, "Case is not in OFF_BYPASS."),
    ("ERR_CASE_NOT_CANCELLABLE", 409, "Case has already reached a terminal state."),
    ("ERR_DEVICE_NOT_AVAILABLE", 409, "Device is not in a reservable state."),
    ("ERR_DEVICE_SERVICE_NOT_PERMITTED", 409, "Device is not in NEEDS_SERVICE."),
    ("ERR_INCIDENT_STATE_INVALID", 409, "Incident report is not in a state that admits this transition."),
    ("ERR_INCIDENT_RETURN_LIMIT", 409, "Incident report has already been returned for information twice."),
    ("ERR_ECMO_RUN_STATE_INVALID", 409, "ECMO run is not in a state that admits this transition."),
    ("ERR_CE_ACTIVITY_STATE_INVALID", 409, "Continuing-education activity is not in a state that admits this adjudication."),
    ("ERR_PACK_APPROVAL_STATE_INVALID", 409, "Disposable pack is not awaiting surgeon approval."),
    ("ERR_CERTIFICATION_NOT_CURRENT", 422, "Perfusionist has no CCP certification in ACTIVE or PROBATION."),
    ("ERR_PERFUSIONIST_NOT_ACTIVE", 422, "Perfusionist employment_status is not ACTIVE."),
    ("ERR_READINESS_BELOW_MINIMUM", 422, "Readiness score is below the admission minimum."),
    ("ERR_DEVICE_FALLBACK_REQUIRED", 409, "Case carries readiness_flag DEVICE_FALLBACK_REQUIRED."),
    ("ERR_SAFETY_CHECKS_INCOMPLETE", 422, "Not every required safety check is present and passed."),
    ("ERR_BLOOD_PROTOCOL_MISMATCH", 422, "Checklist blood_management_protocol does not match the applied preference card."),
    ("ERR_HEMATOCRIT_BELOW_MINIMUM", 422, "Checklist hematocrit_pct is below the preference card minimum."),
    ("ERR_PACK_APPROVAL_PENDING", 409, "Disposable pack approval is still pending."),
    ("ERR_DEVICE_SERVICE_OVERDUE", 422, "Device runtime has reached its service interval."),
    ("ERR_NO_BACKUP_DEVICE_AVAILABLE", 422, "No standby device could be resolved for this case."),
    ("ERR_ECMO_PRIVILEGE_REQUIRED", 422, "Perfusionist is not ECMO privileged."),
    ("ERR_ECMO_STAFFING_BREACH", 409, "Perfusionist is in an ECMO staffing breach."),
    ("ERR_RELIEF_SLOT_INVALID", 422, "The named relief slot does not satisfy the handoff requirements."),
    ("ERR_INCIDENT_CASE_NOT_COMPLETE", 409, "The case has not left the bypass run yet."),
    ("ERR_INVALID_BACKUP_DEVICE", 422, "The backup device is not a distinct device of the same class at the same hospital."),
    ("ERR_DUPLICATE_CODE", 409, "A unique code is already in use."),
    ("ERR_PROCEDURE_SPECIALTY_MISMATCH", 422, "The procedure type is outside the surgeon's specialty."),
    ("ERR_SURGEON_NOT_ACTIVE", 422, "Surgeon status is not ACTIVE."),
    ("ERR_NO_ACTIVE_PREFERENCE_CARD", 422, "No ACTIVE preference card exists for this surgeon and procedure type."),
    ("ERR_INVALID_SUBSTITUTION_LINE", 422, "A substitution names a line_code that is not on the applied card."),
    ("ERR_CROSS_CLAMP_EXCEEDS_PUMP_TIME", 422, "cross_clamp_minutes exceeds pump_time_minutes."),
    ("ERR_INVALID_TIME_WINDOW", 422, "The end of the window is not strictly after its start."),
    ("ERR_CASE_START_IN_PAST", 422, "scheduled_start is earlier than the current logical clock."),
    ("ERR_CLOCK_NOT_MONOTONIC", 422, "current_utc is earlier than the stored logical clock."),
    ("ERR_CE_ACTIVITY_OUTSIDE_CYCLE", 422, "activity_date falls outside the current CCP certification cycle."),
    ("ERR_ROTATION_SLOT_OVERLAP", 409, "The window overlaps an existing live slot of the same type for this perfusionist."),
    ("ERR_NO_COVERING_CALL_SLOT", 422, "No single live call slot covers the whole case window."),
    ("ERR_DEVICE_TURNAROUND_CONFLICT", 409, "The device is already held by a case inside the turnaround buffer."),
    ("ERR_PERFUSIONIST_CONCURRENT_CASE_LIMIT", 409, "The perfusionist's concurrent case limit would be exceeded."),
    ("ERR_CONTRACT_COVERAGE_INSUFFICIENT", 409, "The contract's coverage posture is UNCOVERED."),
    ("ERR_SETTLEMENT_PERIOD_INVALID", 422, "The settlement period is malformed, in the future, or already settled."),
    ("ERR_CONTRACT_CASE_CAP_EXCEEDED", 409, "The contract's monthly case cap would be exceeded."),
    # Named in PRD section 3.9 prose (systemic-finding evidence gate).
    ("ERR_SYSTEMIC_FINDING_UNSUPPORTED", 422, "A SYSTEMIC finding is not supported by this report's severity or reviewed readiness score."),
    ("ERR_NOT_FOUND", 404, "Resource not found."),
    ("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed."),
]

ERROR_STATUS = {e[0]: e[1] for e in _CATALOG}
ERROR_MESSAGE = {e[0]: e[2] for e in _CATALOG}
