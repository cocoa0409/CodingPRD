"""Error catalogue (PRD 5)."""


class ApiError(Exception):
    def __init__(self, error_id, status=None, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        # The catalogue is authoritative: an identifier always carries its
        # documented HTTP status, whatever a call site happens to pass.
        self.status = STATUSES.get(error_id, status or 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


STATUSES = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_UNIT_SCOPE_VIOLATION": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_UNIT_NOT_FOUND": 404,
    "ERR_STANDARD_NOT_FOUND": 404,
    "ERR_CREDENTIAL_NOT_FOUND": 404,
    "ERR_ASSET_NOT_FOUND": 404,
    "ERR_REVIEW_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_FOUND": 404,
    "ERR_RESERVATION_NOT_FOUND": 404,
    "ERR_RUN_NOT_FOUND": 404,
    "ERR_ADMISSION_NOT_FOUND": 404,
    "ERR_MILK_BATCH_NOT_FOUND": 404,
    "ERR_ESCALATION_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_UNIT_VERSION_CONFLICT": 412,
    "ERR_ADMISSION_VERSION_CONFLICT": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_DEPENDENT_STATE_INVALID": 409,
    "ERR_LEVEL_CAPABILITY_INSUFFICIENT": 422,
    "ERR_UNIT_SUSPENDED": 422,
    "ERR_CREW_COMPOSITION_INVALID": 422,
    "ERR_ISOLETTE_NOT_SERVICEABLE": 422,
    "ERR_WEATHER_MINIMUMS_NOT_MET": 422,
    "ERR_STABILIZATION_INCOMPLETE": 422,
    "ERR_DEVELOPMENTAL_BUNDLE_INCOMPLETE": 422,
    "ERR_MILK_NOT_ADMINISTRABLE": 422,
    "ERR_MILK_EXPIRED": 422,
    "ERR_NOT_ELIGIBLE_FOR_FOLLOWUP": 422,
    "ERR_ISOLETTE_UNIT_MISMATCH": 409,
    "ERR_MILK_LABEL_MISMATCH": 409,
    "ERR_MATERNAL_TRANSFER_PREFERENCE": 409,
    "ERR_DUPLICATE_ENROLLMENT": 409,
    "ERR_ISOLETTE_UNAVAILABLE": 409,
    "ERR_ESCALATION_WINDOW_OVERLAP": 409,
    "ERR_APPOINTMENT_OUTSIDE_WINDOW": 409,
    "ERR_PERIOD_INVALID": 409,
    "ERR_DUPLICATE_STANDARD": 409,
    "ERR_REVIEW_ALREADY_OPEN": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_NO_BED_AVAILABLE": 409,
    "ERR_SURGE_THRESHOLD_NOT_MET": 409,
    "ERR_SURGE_NO_STAFFED_CAPACITY": 422,
    "ERR_CLINIC_DAY_FULL": 409,
    "ERR_MILK_VOLUME_EXCEEDED": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required.",
    "ERR_ROLE_NOT_PERMITTED": "The caller's role may not perform this operation.",
    "ERR_UNIT_SCOPE_VIOLATION": "The caller may only act for its own unit.",
    "ERR_INVALID_REQUEST": "The request is malformed.",
    "ERR_UNIT_NOT_FOUND": "The referenced NICU unit does not exist.",
    "ERR_STANDARD_NOT_FOUND": "The referenced designation standard does not exist.",
    "ERR_CREDENTIAL_NOT_FOUND": "The referenced staff credential does not exist.",
    "ERR_ASSET_NOT_FOUND": "The referenced equipment asset does not exist.",
    "ERR_REVIEW_NOT_FOUND": "The referenced designation review does not exist.",
    "ERR_REFERRAL_NOT_FOUND": "The referenced referral does not exist.",
    "ERR_RESERVATION_NOT_FOUND": "The referenced bed reservation does not exist.",
    "ERR_RUN_NOT_FOUND": "The referenced transport run does not exist.",
    "ERR_ADMISSION_NOT_FOUND": "The referenced admission does not exist.",
    "ERR_MILK_BATCH_NOT_FOUND": "The referenced milk batch does not exist.",
    "ERR_ESCALATION_NOT_FOUND": "The referenced surge escalation does not exist.",
    "ERR_REPORT_NOT_FOUND": "The referenced surveillance report does not exist.",
    "ERR_ENROLLMENT_NOT_FOUND": "The referenced follow-up enrollment does not exist.",
    "ERR_UNIT_VERSION_CONFLICT": "expected_unit_version does not match the unit's stored version.",
    "ERR_ADMISSION_VERSION_CONFLICT": "expected_admission_version does not match the admission's stored version.",
    "ERR_INVALID_STATE": "The entity's current status does not permit this operation.",
    "ERR_DEPENDENT_STATE_INVALID": "A related entity is not in the state this operation requires.",
    "ERR_LEVEL_CAPABILITY_INSUFFICIENT": "The receiving unit's effective level is below the referral's required level.",
    "ERR_UNIT_SUSPENDED": "The unit is suspended.",
    "ERR_CREW_COMPOSITION_INVALID": "The transport crew must include TRANSPORT_RN.",
    "ERR_ISOLETTE_NOT_SERVICEABLE": "The isolette is not a serviceable TRANSPORT_ISOLETTE.",
    "ERR_WEATHER_MINIMUMS_NOT_MET": "Aviation weather minimums are not met.",
    "ERR_STABILIZATION_INCOMPLETE": "The stabilization bundle is incomplete.",
    "ERR_DEVELOPMENTAL_BUNDLE_INCOMPLETE": "The developmental bundle score is below 60.",
    "ERR_MILK_NOT_ADMINISTRABLE": "The milk batch is not in an administrable state.",
    "ERR_MILK_EXPIRED": "The milk batch has expired.",
    "ERR_NOT_ELIGIBLE_FOR_FOLLOWUP": "The admission is not eligible for follow-up.",
    "ERR_ISOLETTE_UNIT_MISMATCH": "The isolette belongs to another unit.",
    "ERR_MILK_LABEL_MISMATCH": "The presented label code does not match the batch.",
    "ERR_MATERNAL_TRANSFER_PREFERENCE": "A higher-priority maternal transfer is waiting on the last free bed.",
    "ERR_DUPLICATE_ENROLLMENT": "The admission already has an open follow-up enrollment.",
    "ERR_ISOLETTE_UNAVAILABLE": "The isolette occupation interval overlaps another run.",
    "ERR_ESCALATION_WINDOW_OVERLAP": "The escalation window overlaps another active escalation.",
    "ERR_APPOINTMENT_OUTSIDE_WINDOW": "The appointment falls outside the graduate's appointment window.",
    "ERR_PERIOD_INVALID": "The surveillance period is invalid for this unit.",
    "ERR_DUPLICATE_STANDARD": "A designation standard already exists for that level.",
    "ERR_REVIEW_ALREADY_OPEN": "The unit already has an open designation review.",
    "ERR_SEGREGATION_OF_DUTIES": "The same person may not perform both steps.",
    "ERR_NO_BED_AVAILABLE": "No bed is available at the receiving unit.",
    "ERR_SURGE_THRESHOLD_NOT_MET": "The census ratio is below the surge threshold.",
    "ERR_SURGE_NO_STAFFED_CAPACITY": "No staffed capacity is available for the escalation.",
    "ERR_CLINIC_DAY_FULL": "The clinic's calendar-day capacity is full.",
    "ERR_MILK_VOLUME_EXCEEDED": "The requested volume exceeds the batch ledger.",
}


def invalid_request(message=None):
    return ApiError("ERR_INVALID_REQUEST", 400, message)


def invalid_state(message=None):
    return ApiError("ERR_INVALID_STATE", 409, message)


def dependent_state(message=None):
    return ApiError("ERR_DEPENDENT_STATE_INVALID", 409, message)
