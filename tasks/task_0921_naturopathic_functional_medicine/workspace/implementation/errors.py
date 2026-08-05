"""Error catalogue (34 codes) and the single raise-able exception type."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP[error_id]
        self.message = message or DEFAULT_MESSAGE.get(error_id, error_id)


ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_OWNERSHIP_VIOLATION": 403,
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_PRACTITIONER_NOT_FOUND": 404,
    "ERR_PROTOCOL_NOT_FOUND": 404,
    "ERR_LAB_ORDER_NOT_FOUND": 404,
    "ERR_ENCOUNTER_NOT_FOUND": 404,
    "ERR_MEMBERSHIP_NOT_FOUND": 404,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_ENUM": 422,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_DEPENDENT_STATE_INVALID": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_CLINICAL_WRITE_FROZEN": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INTAKE_INCOMPLETE": 422,
    "ERR_RED_FLAG_UNACKNOWLEDGED": 409,
    "ERR_STATE_NOT_LICENSED": 403,
    "ERR_MODALITY_CONSENT_MISSING": 422,
    "ERR_CONTRAINDICATION_SEVERE": 422,
    "ERR_COLLECTION_WINDOW_INVALID": 422,
    "ERR_WASHOUT_NOT_ELAPSED": 409,
    "ERR_DUPLICATE_PANEL_ORDER": 409,
    "ERR_PRACTITIONER_DOUBLE_BOOKED": 409,
    "ERR_MEMBERSHIP_CYCLE_OVERLAP": 409,
    "ERR_LOT_EXPIRED": 422,
    "ERR_INSUFFICIENT_STOCK": 409,
    "ERR_NO_ELIGIBLE_LOT": 409,
    "ERR_ENTITLEMENT_EXHAUSTED": 402,
    "ERR_SUPERBILL_NOT_BILLABLE": 422,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role may not use this endpoint.",
    "ERR_OWNERSHIP_VIOLATION": "A patient may only act on their own records.",
    "ERR_PATIENT_NOT_FOUND": "Patient not found.",
    "ERR_PRACTITIONER_NOT_FOUND": "Practitioner not found.",
    "ERR_PROTOCOL_NOT_FOUND": "Protocol not found.",
    "ERR_LAB_ORDER_NOT_FOUND": "Lab order not found.",
    "ERR_ENCOUNTER_NOT_FOUND": "Encounter not found.",
    "ERR_MEMBERSHIP_NOT_FOUND": "Membership not found.",
    "ERR_RESOURCE_NOT_FOUND": "Resource not found.",
    "ERR_REFERENCE_NOT_FOUND": "Referenced resource not found.",
    "ERR_VALIDATION": "The request payload failed validation.",
    "ERR_INVALID_ENUM": "An enum-typed field carries a value outside its declared set.",
    "ERR_INVALID_PAGINATION": "limit must be an integer in 1..100 and offset an integer >= 0.",
    "ERR_INVALID_STATE": "The resource is not in a state from which this transition is declared.",
    "ERR_DEPENDENT_STATE_INVALID": "A dependent resource is in the wrong state.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the current version.",
    "ERR_CLINICAL_WRITE_FROZEN": "The patient's clinical write gate is not OPEN.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting user may not be both parties to this decision.",
    "ERR_INTAKE_INCOMPLETE": "The patient's intake completeness score is below the required threshold.",
    "ERR_RED_FLAG_UNACKNOWLEDGED": "The red-flag referral for this order has not been acknowledged.",
    "ERR_STATE_NOT_LICENSED": "The practitioner is not licensed in the patient's state.",
    "ERR_MODALITY_CONSENT_MISSING": "The patient has not consented to remote care.",
    "ERR_CONTRAINDICATION_SEVERE": "A protocol line carries a SEVERE interaction with a reported medication class.",
    "ERR_COLLECTION_WINDOW_INVALID": "The panel's collection window requirements are not satisfied.",
    "ERR_WASHOUT_NOT_ELAPSED": "The supplement wash-out has not elapsed.",
    "ERR_DUPLICATE_PANEL_ORDER": "The patient already holds an open order for this panel.",
    "ERR_PRACTITIONER_DOUBLE_BOOKED": "The requested window collides with another encounter of this practitioner.",
    "ERR_MEMBERSHIP_CYCLE_OVERLAP": "The requested membership cycle overlaps a live cycle of this patient.",
    "ERR_LOT_EXPIRED": "The named lot is quarantined or expired.",
    "ERR_INSUFFICIENT_STOCK": "The named lot holds fewer units than requested.",
    "ERR_NO_ELIGIBLE_LOT": "No eligible lot holds the requested quantity.",
    "ERR_ENTITLEMENT_EXHAUSTED": "The patient has no active membership with sufficient laboratory credits.",
    "ERR_SUPERBILL_NOT_BILLABLE": "The superbill does not document billable cash.",
}
