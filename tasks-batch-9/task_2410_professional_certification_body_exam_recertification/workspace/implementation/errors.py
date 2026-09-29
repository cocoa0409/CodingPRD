"""Error catalogue (PRD section 5) and the ApiError exception."""


ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED":                 (401, "Missing or empty X-User-ID header"),
    "ERR_FORBIDDEN_ROLE":                  (403, "X-User-Role is not permitted on this endpoint"),
    "ERR_NOT_RESOURCE_OWNER":              (403, "Acting user does not own the addressed resource"),
    "ERR_INVALID_REQUEST":                 (400, "Malformed body: missing required field, bad enum, or out-of-range value"),
    "ERR_STALE_VERSION":                   (412, "expected_<parent>_version does not match the parent's current version"),
    "ERR_PROGRAM_NOT_FOUND":               (404, "No CertificationProgram with that id"),
    "ERR_ITEM_NOT_FOUND":                  (404, "No Item with that id"),
    "ERR_FORM_NOT_FOUND":                  (404, "No ExamForm with that id"),
    "ERR_CANDIDATE_NOT_FOUND":             (404, "No Candidate with that id"),
    "ERR_APPLICATION_NOT_FOUND":           (404, "No EligibilityApplication with that id"),
    "ERR_SESSION_NOT_FOUND":               (404, "No ExamSession with that id"),
    "ERR_REGISTRATION_NOT_FOUND":          (404, "No ExamRegistration with that id"),
    "ERR_INCIDENT_NOT_FOUND":              (404, "No SecurityIncident with that id"),
    "ERR_CERTIFICANT_NOT_FOUND":           (404, "No Certificant with that id, or the credential is suppressed from the public registry"),
    "ERR_CYCLE_NOT_FOUND":                 (404, "No RecertificationCycle with that id"),
    "ERR_ACTIVITY_NOT_FOUND":              (404, "No CEUActivity with that id"),
    "ERR_CASE_NOT_FOUND":                  (404, "No DisciplinaryCase with that id"),
    "ERR_CREDENTIAL_CODE_TAKEN":           (409, "Another DRAFT or ACTIVE program already uses this credential_code"),
    "ERR_CANDIDATE_EMAIL_TAKEN":           (409, "Another candidate already uses this email"),
    "ERR_BLUEPRINT_WEIGHTS_INVALID":       (400, "domain_specs weights must sum to exactly 100 with unique domain codes"),
    "ERR_INVALID_STATE":                   (409, "The entity's current state does not permit this transition"),
    "ERR_PROGRAM_NOT_ACTIVE":              (409, "The certification program is not ACTIVE"),
    "ERR_FORM_NOT_PUBLISHED":              (409, "The exam form is not PUBLISHED"),
    "ERR_APPLICATION_NOT_APPROVED":        (409, "The eligibility application is not APPROVED"),
    "ERR_CERTIFICANT_NOT_ACTIVE":          (409, "The certificant is suspended, expired or revoked"),
    "ERR_CERTIFICANT_ALREADY_REVOKED":     (409, "The credential is already revoked and admits no further action"),
    "ERR_DIMENSION_ALREADY_VERIFIED":      (409, "That eligibility dimension has already been decided"),
    "ERR_SEGREGATION_OF_DUTIES":           (409, "The acting user already holds an incompatible role on this record"),
    "ERR_CANDIDATE_BARRED":                (409, "The candidate is barred from testing"),
    "ERR_SCORE_UNDER_SECURITY_HOLD":       (409, "An unresolved security incident blocks this score operation"),
    "ERR_ITEM_DOMAIN_MISMATCH":            (422, "Item belongs to another program or to a domain outside the blueprint"),
    "ERR_ITEM_NOT_ELIGIBLE_FOR_FORM":      (422, "Item is not in a form-eligible status"),
    "ERR_ITEM_NOT_IN_FORM":                (422, "pretest_item_ids must be a subset of item_ids"),
    "ERR_PANELIST_NOT_ON_PANEL":           (422, "The rater is not a panelist on this form"),
    "ERR_ELIGIBILITY_PROGRAM_MISMATCH":    (422, "The form and the application belong to different programs"),
    "ERR_ROOM_WINDOW_CONFLICT":            (409, "Another test-centre session already occupies that room window"),
    "ERR_CANDIDATE_WINDOW_CONFLICT":       (409, "The candidate already sits an exam within the 120-minute buffer of that window"),
    "ERR_SESSION_CLOSED":                  (409, "The session has already started"),
    "ERR_CHECKIN_WINDOW_CLOSED":           (409, "Check-in is only permitted from 30 minutes before start until the session ends"),
    "ERR_ELIGIBILITY_EXPIRED":             (409, "The application's eligibility period has elapsed"),
    "ERR_RETAKE_WAIT_ACTIVE":              (409, "The mandatory wait since the last attempt has not elapsed"),
    "ERR_ACTIVITY_OUTSIDE_CYCLE":          (422, "The activity date falls outside the cycle's accrual window"),
    "ERR_BLUEPRINT_DEFICIENT":             (422, "One or more blueprint domains lack the minimum operational items"),
    "ERR_FORM_LENGTH_MISMATCH":            (422, "item_ids length does not equal the program's form_length"),
    "ERR_PANEL_QUORUM_NOT_MET":            (422, "Too few panellist ratings to adopt a cut score after trimming"),
    "ERR_DUPLICATE_PANELIST_RATING":       (409, "That panellist has already rated this form"),
    "ERR_MAX_ATTEMPTS_REACHED":            (422, "The application has consumed its permitted attempts"),
    "ERR_CREDITS_NOT_SATISFIED":           (422, "The cycle has not met its credit or re-examination requirement"),
    "ERR_DUE_PROCESS_INCOMPLETE":          (422, "A sanction or revocation requires at least one completed response round"),
    "ERR_RAW_SCORE_OUT_OF_RANGE":          (422, "raw_score must be between 0 and the form's scored_item_count"),
    "ERR_ITEM_NOT_ELIGIBLE_FOR_STATS":     (422, "The item cannot accept response data in its current status"),
    "ERR_ITEM_NOT_OPERATIONAL":            (422, "Every scored position must resolve to an OPERATIONAL item"),
    "ERR_EXAM_FEE_INSUFFICIENT":           (402, "fee_paid_cents is below the program's exam fee"),
    "ERR_REINSTATEMENT_FEE_UNPAID":        (402, "payment_cents is below the assessed reinstatement fee"),
    "ERR_SESSION_FULL":                    (409, "The session has no remaining seats"),
    "ERR_PROCTOR_POOL_CAPACITY_EXCEEDED":  (409, "Overlapping online-proctored sessions would exceed the pool's concurrent seat ceiling"),
}


class ApiError(Exception):
    """Raised anywhere in a handler to abort with the standard error envelope."""

    def __init__(self, error_id, message=None):
        status, default_message = ERROR_CATALOG[error_id]
        super().__init__(message or default_message)
        self.error_id = error_id
        self.http_status = status
        self.message = message or default_message
