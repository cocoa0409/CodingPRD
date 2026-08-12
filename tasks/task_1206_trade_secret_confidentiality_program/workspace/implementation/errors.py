"""Error model: every failure carries the scaffold's exact error_id and HTTP
status (SCAFFOLD §1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# -- Error catalog (verbatim ids/statuses from SCAFFOLD §1.6) ----------------
def err_unauthenticated(msg="Missing X-User-Role / X-User-ID or undeclared role"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_unauthorized_role(msg="Role not permitted for this endpoint or transition"):
    return ApiError("ERR_UNAUTHORIZED_ROLE", 403, msg)


def err_ownership(msg="Actor identity must equal the owning entity id"):
    return ApiError("ERR_OWNERSHIP_REQUIRED", 403, msg)


def err_sod(msg="Same user attempted both sides of a controlled step"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


def err_not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_stale_version(msg="Expected version does not match the current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def err_invalid_state(msg="Transition undefined from current state or state gate failed"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_invalid_request(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_duplicate_email(msg="Employee email already exists"):
    return ApiError("ERR_DUPLICATE_EMAIL", 409, msg)


def err_date_order(msg="Window end must be strictly after its start"):
    return ApiError("ERR_DATE_ORDER", 422, msg)


def err_expiry_in_past(msg="Grant expires_at must be later than now and no more than 365 days out"):
    return ApiError("ERR_EXPIRY_IN_PAST", 422, msg)


def err_review_window_expired(msg="Forensic review opened more than 90 days after departure"):
    return ApiError("ERR_REVIEW_WINDOW_EXPIRED", 422, msg)


def err_nda_window_overlap(msg="NDA window overlaps another non-terminal NDA of the same counterparty"):
    return ApiError("ERR_NDA_WINDOW_OVERLAP", 409, msg)


def err_audit_window_conflict(msg="Department has another non-terminal audit within the 7-day buffer"):
    return ApiError("ERR_AUDIT_WINDOW_CONFLICT", 409, msg)


def err_interview_overlap(msg="Interview window overlaps another scheduled/conducted interview"):
    return ApiError("ERR_INTERVIEW_OVERLAP", 409, msg)


def err_need_to_know(msg="Employee access_clearance below the asset classification requirement"):
    return ApiError("ERR_NEED_TO_KNOW_VIOLATION", 403, msg)


def err_ceiling(msg="Asset classification exceeds the NDA classification_ceiling"):
    return ApiError("ERR_CLASSIFICATION_CEILING_EXCEEDED", 409, msg)


def err_posture(msg="Asset protection_posture is DEFICIENT"):
    return ApiError("ERR_POSTURE_DEFICIENT", 409, msg)


def err_preservation(msg="An ISSUED/ACTIVE preservation notice covers the target"):
    return ApiError("ERR_PRESERVATION_HOLD_ACTIVE", 409, msg)


def err_risk_too_high(msg="Final disclosure risk score is 95 or more; approval forbidden"):
    return ApiError("ERR_DISCLOSURE_RISK_TOO_HIGH", 409, msg)


def err_endorsement(msg="Final disclosure risk score is 80 or more and senior_endorsed is false"):
    return ApiError("ERR_ENDORSEMENT_REQUIRED", 409, msg)


def err_nda_not_active(msg="Referenced NDA is not ACTIVE"):
    return ApiError("ERR_NDA_NOT_ACTIVE", 409, msg)


def err_counterparty_not_active(msg="Counterparty is not ACTIVE"):
    return ApiError("ERR_COUNTERPARTY_NOT_ACTIVE", 409, msg)


def err_stale_reference(msg="Pinned asset or NDA version is no longer current"):
    return ApiError("ERR_STALE_REFERENCE", 409, msg)


def err_ack_required(msg="No SIGNED acknowledgment on the current policy version"):
    return ApiError("ERR_ACK_REQUIRED", 409, msg)


def err_policy_stale(msg="Acknowledgment policy_version is not the program's current version"):
    return ApiError("ERR_POLICY_VERSION_STALE", 409, msg)


def err_interview_not_certified(msg="Departure requires a CERTIFIED exit interview"):
    return ApiError("ERR_EXIT_INTERVIEW_NOT_CERTIFIED", 409, msg)


def err_grants_remain(msg="Active access grants remain"):
    return ApiError("ERR_ACTIVE_GRANTS_REMAIN", 409, msg)


def err_review_not_concluded(msg="A forensic review has not concluded"):
    return ApiError("ERR_REVIEW_NOT_CONCLUDED", 409, msg)


def err_training_not_current(msg="Employee training_current is false"):
    return ApiError("ERR_TRAINING_NOT_CURRENT", 409, msg)


def err_measure_evidence(msg="IMPLEMENTED requires a non-empty evidence_uri"):
    return ApiError("ERR_MEASURE_EVIDENCE_REQUIRED", 422, msg)


def err_marking_evidence(msg="EXECUTED requires marking_evidence_uri and a well-formed marking_sha256"):
    return ApiError("ERR_MARKING_EVIDENCE_REQUIRED", 422, msg)


def err_invalid_hash(msg="sha256 must be exactly 64 lowercase hexadecimal characters"):
    return ApiError("ERR_INVALID_HASH", 422, msg)
