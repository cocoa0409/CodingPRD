"""Error classes carrying error_id + http_status from the scaffold error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err_missing_context(msg="X-User-ID or X-User-Role header missing, or role not declared"):
    return ApiError("ERR_MISSING_CONTEXT_HEADER", 400, msg)


def err_forbidden_role(msg="Caller role not in the endpoint's roles list"):
    return ApiError("ERR_FORBIDDEN_ROLE", 403, msg)


def err_device_identity(msg="GateDevice X-User-ID does not equal the device id acted upon"):
    return ApiError("ERR_DEVICE_IDENTITY_MISMATCH", 403, msg)


def err_not_owner(msg="Caller does not own the resource"):
    return ApiError("ERR_NOT_OWNER", 403, msg)


def err_segregation(msg="Reconciliation actor must differ from the shift's attendant_user_id"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


def err_not_found(msg="Path resource id does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_ref_not_found(msg="Body reference id does not exist"):
    return ApiError("ERR_REFERENCE_NOT_FOUND", 404, msg)


def err_validation(msg="Missing required field, invalid enum value, or numeric range violation"):
    return ApiError("ERR_VALIDATION", 400, msg)


def err_stale_facility(msg="expected_facility_version behind current Facility.version"):
    return ApiError("ERR_STALE_FACILITY_VERSION", 412, msg)


def err_stale_agreement(msg="expected_agreement_version behind current MonthlyAgreement.version"):
    return ApiError("ERR_STALE_AGREEMENT_VERSION", 412, msg)


def err_invalid_state(msg="Current state does not permit the requested transition"):
    return ApiError("ERR_INVALID_STATE_TRANSITION", 409, msg)


def err_posture_blocks(msg="Facility posture blocks the action"):
    return ApiError("ERR_FACILITY_POSTURE_BLOCKS", 409, msg)


def err_posture_blocked(msg="Manual posture target illegal or guard violated"):
    return ApiError("ERR_POSTURE_TRANSITION_BLOCKED", 409, msg)


def err_structural_critical(msg="Posture release blocked by a REPORTED CRITICAL structural inspection"):
    return ApiError("ERR_STRUCTURAL_CRITICAL", 409, msg)


def err_device_not_online(msg="Entry device not ONLINE or not of this facility"):
    return ApiError("ERR_DEVICE_NOT_ONLINE", 409, msg)


def err_no_published_rate(msg="No PUBLISHED rate schedule with effective_from <= now for the facility"):
    return ApiError("ERR_NO_PUBLISHED_RATE", 409, msg)


def err_shift_not_open(msg="CASH pay/comp requires an OPEN shift at this facility owned by the caller"):
    return ApiError("ERR_SHIFT_NOT_OPEN", 409, msg)


def err_shift_already_open(msg="Attendant already has an OPEN shift at this facility"):
    return ApiError("ERR_SHIFT_ALREADY_OPEN", 409, msg)


def err_exit_unpaid(msg="Exit attempted with billing OPEN/QUOTED and a positive computed fee"):
    return ApiError("ERR_EXIT_UNPAID", 409, msg)


def err_duplicate_ticket(msg="ticket_barcode already in use by a PARKED session of this facility"):
    return ApiError("ERR_DUPLICATE_TICKET", 409, msg)


def err_credential_not_valid(msg="Credential not ACTIVE or its agreement not ACTIVE at credentialed entry"):
    return ApiError("ERR_CREDENTIAL_NOT_VALID", 409, msg)


def err_credential_limit(msg="Agreement already has 2 credentials in {ACTIVE, LOST_REPORTED}"):
    return ApiError("ERR_CREDENTIAL_LIMIT", 409, msg)


def err_agreement_not_issuable(msg="Credential issuance requires agreement APPROVED or ACTIVE"):
    return ApiError("ERR_AGREEMENT_NOT_ISSUABLE", 409, msg)


def err_credentials_outstanding(msg="Terminate blocked: credentials still ACTIVE or LOST_REPORTED"):
    return ApiError("ERR_CREDENTIALS_OUTSTANDING", 409, msg)


def err_charger_unavailable(msg="Charger not COMMISSIONED, already has a CHARGING session, or supplied agreement not ACTIVE"):
    return ApiError("ERR_CHARGER_UNAVAILABLE", 409, msg)


def err_staffing(msg="len(staffing_assignments) < min_staff at event confirm"):
    return ApiError("ERR_STAFFING_INSUFFICIENT", 409, msg)


def err_safety_hold(msg="Window on a level with a REPORTED CRITICAL inspection without safety_authorized=true"):
    return ApiError("ERR_SAFETY_HOLD", 409, msg)


def err_invalid_time_range(msg="end_at <= start_at, or event activation outside [start_at, end_at)"):
    return ApiError("ERR_INVALID_TIME_RANGE", 400, msg)


def err_window_overlap(msg="Window collides with another SCHEDULED/IN_PROGRESS window on the same facility+level"):
    return ApiError("ERR_WINDOW_OVERLAP", 409, msg)


def err_event_pool(msg="Combined presale_allocation of overlapping CONFIRMED/ACTIVE events would exceed event_pool_spaces"):
    return ApiError("ERR_EVENT_POOL_EXCEEDED", 409, msg)


def err_monthly_pool(msg="Activation while count(ACTIVE+SUSPENDED) == monthly_capacity"):
    return ApiError("ERR_MONTHLY_POOL_EXHAUSTED", 409, msg)


def err_comp_limit(msg="Shift comp_total_cents + waived fee would exceed COMP_CAP_PER_SHIFT_CENTS (5000)"):
    return ApiError("ERR_COMP_LIMIT_EXCEEDED", 422, msg)


def err_refund_exceeds(msg="refund amount_cents > settled_fee_cents"):
    return ApiError("ERR_REFUND_EXCEEDS_COLLECTED", 422, msg)


def err_insufficient_reserve(msg="Repair draw exceeds Facility.capital_reserve_cents"):
    return ApiError("ERR_INSUFFICIENT_RESERVE", 422, msg)


def err_variance_incident(msg="Approve from VARIANCE_REVIEW without a valid linked INVESTIGATING CASH_VARIANCE incident_id"):
    return ApiError("ERR_VARIANCE_INCIDENT_REQUIRED", 409, msg)


def err_inspection_not_reported(msg="Repair funding references an inspection not yet REPORTED"):
    return ApiError("ERR_INSPECTION_NOT_REPORTED", 409, msg)
