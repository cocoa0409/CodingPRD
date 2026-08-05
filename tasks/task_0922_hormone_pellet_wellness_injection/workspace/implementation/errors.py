"""Error catalogue (PRD section 5) and the exception that carries it."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP_STATUS[error_id]
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_HTTP_STATUS = {
    # authentication and authorisation
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_FORBIDDEN_OWNERSHIP": 403,
    "ERR_STANDING_ORDER_INVALID": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_SERIES_NOT_TRANSFERABLE": 403,
    # request shape
    "ERR_VALIDATION": 400,
    "ERR_INVALID_ENUM": 400,
    # existence
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_PROVIDER_NOT_FOUND": 404,
    "ERR_PROTOCOL_NOT_FOUND": 404,
    "ERR_CONSENT_NOT_FOUND": 404,
    "ERR_CONSULT_NOT_FOUND": 404,
    "ERR_LAB_PANEL_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_STANDING_ORDER_NOT_FOUND": 404,
    "ERR_PROCEDURE_NOT_FOUND": 404,
    "ERR_INJECTION_VISIT_NOT_FOUND": 404,
    "ERR_MEMBERSHIP_NOT_FOUND": 404,
    "ERR_SERIES_PACK_NOT_FOUND": 404,
    "ERR_ADVERSE_EVENT_NOT_FOUND": 404,
    "ERR_FINANCING_PLAN_NOT_FOUND": 404,
    "ERR_NOTIFICATION_NOT_FOUND": 404,
    # state and concurrency
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_STALE_PATIENT_VERSION": 412,
    "ERR_STALE_PROCEDURE_VERSION": 412,
    "ERR_STALE_MEMBERSHIP_VERSION": 412,
    # clinical safety
    "ERR_PATIENT_CLINICAL_HOLD": 409,
    "ERR_CRITICAL_LAB_UNACKNOWLEDGED": 409,
    "ERR_CONSENT_REQUIRED": 409,
    "ERR_CONSENT_DOSE_EXCEEDED": 422,
    "ERR_SAFETY_CEILING_EXCEEDED": 422,
    "ERR_DOSE_CAP_EXCEEDED": 422,
    "ERR_ROLLING_MG_CAP_EXCEEDED": 422,
    # re-dose gate
    "ERR_LAB_STALE": 422,
    "ERR_TROUGH_WINDOW_VIOLATION": 422,
    "ERR_REDOSE_INTERVAL_NOT_MET": 422,
    "ERR_ANALYTE_NOT_BELOW_OPTIMAL": 422,
    "ERR_SYMPTOM_SCORE_BELOW_THRESHOLD": 422,
    # scheduling
    "ERR_POST_INSERTION_RESTRICTION": 409,
    "ERR_PROVIDER_SLOT_CONFLICT": 409,
    "ERR_ROOM_CONFLICT": 409,
    # inventory
    "ERR_LOT_NOT_ELIGIBLE": 409,
    "ERR_INSUFFICIENT_PELLET_INVENTORY": 409,
    # entitlement pools
    "ERR_SERIES_EXPIRED": 409,
    "ERR_SERIES_EXHAUSTED": 409,
    "ERR_DUPLICATE_ACTIVE_MEMBERSHIP": 409,
    "ERR_PAUSE_LIMIT_EXCEEDED": 422,
    # fiscal
    "ERR_DOWN_PAYMENT_TOO_LOW": 422,
    "ERR_INSTALLMENT_COUNT_INVALID": 422,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
    "ERR_PATIENT_FINANCIAL_HOLD": 402,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role must both be present and name a declared role.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorised on this endpoint.",
    "ERR_FORBIDDEN_OWNERSHIP": "The acting identity does not own the addressed row.",
    "ERR_STANDING_ORDER_INVALID": "The governing standing order does not authorise this administration.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this reviewer.",
    "ERR_SERIES_NOT_TRANSFERABLE": "A series pack may not be applied to another patient's visit.",
    "ERR_VALIDATION": "The request payload failed validation.",
    "ERR_INVALID_ENUM": "An enum-valued input field carried an undeclared member.",
    "ERR_INVALID_STATE": "The requested transition is not declared from the current state.",
    "ERR_ALREADY_TERMINAL": "The target row is already in a terminal state for this axis.",
    "ERR_STALE_PATIENT_VERSION": "expected_patient_version does not match the patient's current version.",
    "ERR_STALE_PROCEDURE_VERSION": "expected_procedure_version does not match the procedure's current version.",
    "ERR_STALE_MEMBERSHIP_VERSION": "expected_membership_version does not match the membership's current version.",
    "ERR_PATIENT_CLINICAL_HOLD": "The patient is under a clinical hold.",
    "ERR_CRITICAL_LAB_UNACKNOWLEDGED": "The patient holds an unacknowledged critical laboratory value.",
    "ERR_CONSENT_REQUIRED": "A current, active consent for this patient and hormone is required.",
    "ERR_CONSENT_DOSE_EXCEEDED": "The consent does not cover the procedure's planned total milligrams.",
    "ERR_SAFETY_CEILING_EXCEEDED": "The patient's most recent hematocrit exceeds the safety ceiling.",
    "ERR_DOSE_CAP_EXCEEDED": "planned_total_mg exceeds the per-procedure cap for this hormone.",
    "ERR_ROLLING_MG_CAP_EXCEEDED": "The rolling 365-day exposure cap would be exceeded.",
    "ERR_LAB_STALE": "The supporting laboratory panel is too old to support a re-dose.",
    "ERR_TROUGH_WINDOW_VIOLATION": "The supporting panel is not a trough draw inside the hormone's window.",
    "ERR_REDOSE_INTERVAL_NOT_MET": "The minimum re-dose interval has not elapsed.",
    "ERR_ANALYTE_NOT_BELOW_OPTIMAL": "The supporting panel is not below the clinic optimal band for the primary analyte.",
    "ERR_SYMPTOM_SCORE_BELOW_THRESHOLD": "The consult's symptom score is below the re-dose threshold.",
    "ERR_POST_INSERTION_RESTRICTION": "The slot falls inside the post-insertion restriction window.",
    "ERR_PROVIDER_SLOT_CONFLICT": "The provider is already occupied around this slot.",
    "ERR_ROOM_CONFLICT": "The room is already occupied during this slot.",
    "ERR_LOT_NOT_ELIGIBLE": "strength_mg is not a rung of the pellet ladder for this hormone.",
    "ERR_INSUFFICIENT_PELLET_INVENTORY": "The allocation walk cannot satisfy the plan in full.",
    "ERR_SERIES_EXPIRED": "The series pack is past its validity window.",
    "ERR_SERIES_EXHAUSTED": "The series pack has no remaining entitlements.",
    "ERR_DUPLICATE_ACTIVE_MEMBERSHIP": "The patient already holds a live membership.",
    "ERR_PAUSE_LIMIT_EXCEEDED": "Resuming would exceed the annual pause allowance.",
    "ERR_DOWN_PAYMENT_TOO_LOW": "down_payment_cents does not satisfy the minimum down-payment rule.",
    "ERR_INSTALLMENT_COUNT_INVALID": "installment_count is outside the permitted range.",
    "ERR_PAYMENT_AMOUNT_MISMATCH": "The payment does not exactly settle the addressed installment.",
    "ERR_PATIENT_FINANCIAL_HOLD": "The patient is under a financial hold.",
}

# Per-entity not-found code, used by rungs 6 and 7.
NOT_FOUND = {
    "Patient": "ERR_PATIENT_NOT_FOUND",
    "Provider": "ERR_PROVIDER_NOT_FOUND",
    "Protocol": "ERR_PROTOCOL_NOT_FOUND",
    "ConsentRecord": "ERR_CONSENT_NOT_FOUND",
    "Consult": "ERR_CONSULT_NOT_FOUND",
    "LabPanel": "ERR_LAB_PANEL_NOT_FOUND",
    "PelletLot": "ERR_LOT_NOT_FOUND",
    "StandingOrder": "ERR_STANDING_ORDER_NOT_FOUND",
    "Procedure": "ERR_PROCEDURE_NOT_FOUND",
    "InjectionVisit": "ERR_INJECTION_VISIT_NOT_FOUND",
    "Membership": "ERR_MEMBERSHIP_NOT_FOUND",
    "SeriesPack": "ERR_SERIES_PACK_NOT_FOUND",
    "AdverseEvent": "ERR_ADVERSE_EVENT_NOT_FOUND",
    "FinancingPlan": "ERR_FINANCING_PLAN_NOT_FOUND",
    "PatientNotification": "ERR_NOTIFICATION_NOT_FOUND",
}
