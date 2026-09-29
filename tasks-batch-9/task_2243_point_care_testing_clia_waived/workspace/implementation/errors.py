"""Error catalog (PRD 5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID or X-User-Role header missing or role not recognised.",
    "ERR_UNAUTHORIZED": "The acting role is not permitted to perform this operation.",
    "ERR_SITE_NOT_FOUND": "The referenced test site does not exist.",
    "ERR_OPERATOR_NOT_FOUND": "The referenced operator does not exist.",
    "ERR_DEVICE_NOT_FOUND": "The referenced device does not exist.",
    "ERR_REAGENT_LOT_NOT_FOUND": "The referenced reagent lot does not exist.",
    "ERR_RESOURCE_NOT_FOUND": "The referenced resource does not exist.",
    "ERR_INVALID_REQUEST": "The request body or query string is malformed.",
    "ERR_MANUAL_ENTRY_REASON_REQUIRED": "manual_entry_reason is required for MANUAL entry mode.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the stored version.",
    "ERR_CERTIFICATE_NOT_ACTIVE": "The certificate is not ACTIVE.",
    "ERR_DEVICE_QC_LOCKED": "The device is not ACTIVE.",
    "ERR_SITE_OVERSIGHT_SUSPENDED": "The site oversight posture is SUSPENDED.",
    "ERR_LOT_QUARANTINED": "The reagent lot is quarantined, discarded or rejected.",
    "ERR_LOT_NOT_VERIFIED": "The reagent lot is not VERIFIED.",
    "ERR_PT_EVENT_ALREADY_GRADED": "The proficiency event is not PENDING.",
    "ERR_PT_ENROLLMENT_STATUS_INVALID": "The proficiency enrollment is not ENROLLED.",
    "ERR_DEFICIENCY_NOT_CORRECTABLE": "The deficiency finding is not in a correctable state.",
    "ERR_INSPECTION_NOT_IN_PROGRESS": "The inspection is not in the required status.",
    "ERR_ASSESSMENT_NOT_SUBMITTED": "The competency assessment is not SUBMITTED.",
    "ERR_INVALID_STATE": "The requested transition is not available from the current state.",
    "ERR_OPERATOR_ACCESS_LOCKED": "The operator access_status is not ACTIVE.",
    "ERR_OPERATOR_COMPETENCY_LAPSED": "The operator competency_status does not permit this operation.",
    "ERR_REAGENT_LOT_EXPIRED": "The reagent lot expiration_date is in the past.",
    "ERR_QC_OVERDUE": "Quality control for this device is overdue.",
    "ERR_TEMP_EXCURSION_ACTIVE": "The storage unit has an open temperature excursion.",
    "ERR_CERTIFICATE_EXPIRED": "No in-window ACTIVE certificate coverage for this site.",
    "ERR_COVERAGE_OUTSIDE_CERTIFICATE_WINDOW": "The coverage window falls outside the certificate window.",
    "ERR_LOT_DEVICE_MODEL_MISMATCH": "The reagent lot device_model does not match the device.",
    "ERR_CROSS_SITE_REFERENCE": "Cross-referenced rows belong to different test sites.",
    "ERR_QC_RUN_DEVICE_MISMATCH": "The referenced QC run does not belong to the expected device or lot.",
    "ERR_COMPLEXITY_SCOPE_EXCEEDED": "The device complexity class exceeds the permitted complexity.",
    "ERR_INSUFFICIENT_COMPETENCY_METHODS": "Fewer than six competency methods were demonstrated.",
    "ERR_DIRECTOR_NOT_QUALIFIED": "The nominated laboratory director is not qualified.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting user may not both perform and approve this action.",
    "ERR_MANUAL_ENTRY_NOT_PERMITTED": "Manual result entry is suspended for this site or device.",
    "ERR_COVERAGE_WINDOW_OVERLAP": "The coverage window overlaps an existing coverage for this site.",
    "ERR_ASSESSMENT_WINDOW_OVERLAP": "The assessment window overlaps an approved assessment.",
    "ERR_DUPLICATE_ENROLLMENT": "An enrollment already exists for this site, analyte and program year.",
}


def err(error_id, http_status, message=None):
    return ApiError(error_id, http_status, message)


def unauthenticated():
    return ApiError("ERR_UNAUTHENTICATED", 401)


def unauthorized():
    return ApiError("ERR_UNAUTHORIZED", 403)


def invalid_request(message=None):
    return ApiError("ERR_INVALID_REQUEST", 400, message)


def invalid_state(message=None):
    return ApiError("ERR_INVALID_STATE", 409, message)
