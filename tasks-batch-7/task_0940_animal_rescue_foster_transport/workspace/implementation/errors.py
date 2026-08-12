"""The closed error catalogue (PRD section 5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)
        self.http_status = HTTP[error_id]


HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_ENUM": 400,
    "ERR_ORGANIZATION_NOT_FOUND": 404,
    "ERR_PERSON_NOT_FOUND": 404,
    "ERR_ANIMAL_NOT_FOUND": 404,
    "ERR_LITTER_NOT_FOUND": 404,
    "ERR_INTAKE_RECORD_NOT_FOUND": 404,
    "ERR_HOLD_NOT_FOUND": 404,
    "ERR_FOSTER_HOME_NOT_FOUND": 404,
    "ERR_FOSTER_APPLICATION_NOT_FOUND": 404,
    "ERR_FOSTER_PLACEMENT_NOT_FOUND": 404,
    "ERR_MEDICAL_RESOURCE_NOT_FOUND": 404,
    "ERR_TRANSPORT_RESOURCE_NOT_FOUND": 404,
    "ERR_ADOPTION_RESOURCE_NOT_FOUND": 404,
    "ERR_FUNDING_RESOURCE_NOT_FOUND": 404,
    "ERR_RECORDS_FROZEN": 409,
    "ERR_ANIMAL_OUTCOME_CLOSED": 409,
    "ERR_LEGAL_HOLD_ACTIVE": 409,
    "ERR_MEDICAL_HOLD_ACTIVE": 409,
    "ERR_BEHAVIORAL_HOLD_ACTIVE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_HOLD_ALREADY_EXPIRED": 409,
    "ERR_STRAY_HOLD_NOT_EXPIRED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_ALTERATION_REQUIRED": 422,
    "ERR_HOUSEHOLD_MISMATCH": 422,
    "ERR_APPLICATION_ATTEMPT_LIMIT": 409,
    "ERR_HOME_CHECK_NOT_CURRENT": 409,
    "ERR_FOSTER_CAPACITY_EXCEEDED": 409,
    "ERR_FOSTER_HEADCOUNT_EXCEEDED": 409,
    "ERR_FOSTER_RESTRICTION_VIOLATION": 422,
    "ERR_LEG_CRATE_CAPACITY_EXCEEDED": 409,
    "ERR_LEG_WEIGHT_CAPACITY_EXCEEDED": 409,
    "ERR_SPECIES_INCOMPATIBLE_LEG": 422,
    "ERR_LEG_SEQUENCE_VIOLATION": 409,
    "ERR_DRIVER_LEG_OVERLAP": 409,
    "ERR_CVI_REQUIRED": 422,
    "ERR_CVI_EXPIRED": 409,
    "ERR_RABIES_AGE_NOT_MET": 422,
    "ERR_LITTER_SPLIT_NOT_APPROVED": 409,
    "ERR_PARTNER_COMMITMENT_UNAVAILABLE": 409,
    "ERR_PARTNER_SPECIES_MISMATCH": 422,
    "ERR_RESTRICTED_FUND_CATEGORY_MISMATCH": 422,
    "ERR_INSUFFICIENT_RESTRICTED_FUNDS": 409,
    "ERR_RETURN_WINDOW_CLOSED": 409,
}

_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing, empty or name an unrecognised role.",
    "ERR_UNAUTHORIZED": "The acting role is not authorised for this operation or resource.",
    "ERR_VALIDATION": "The request failed a structural, numeric or format constraint.",
    "ERR_INVALID_ENUM": "An enum-typed field carries a value outside its declared members.",
    "ERR_RECORDS_FROZEN": "The owning organization is under a records freeze.",
    "ERR_ANIMAL_OUTCOME_CLOSED": "The animal's custody is already closed by a standing outcome.",
    "ERR_LEGAL_HOLD_ACTIVE": "An active legal hold restrains this animal.",
    "ERR_MEDICAL_HOLD_ACTIVE": "An active medical hold restrains this animal.",
    "ERR_BEHAVIORAL_HOLD_ACTIVE": "An active behavioural hold restrains this animal.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the parent's current version.",
    "ERR_INVALID_STATE": "No declared transition exists out of the current state for this trigger.",
}

# PRD 2.11 -- the closed not-found entity map.  The error code for a missing row
# is fixed by the entity alone: not by the endpoint, not by the caller's role.
NOT_FOUND = {
    "Organization": "ERR_ORGANIZATION_NOT_FOUND",
    "Person": "ERR_PERSON_NOT_FOUND",
    "Animal": "ERR_ANIMAL_NOT_FOUND",
    "Litter": "ERR_LITTER_NOT_FOUND",
    "IntakeRecord": "ERR_INTAKE_RECORD_NOT_FOUND",
    "HoldRecord": "ERR_HOLD_NOT_FOUND",
    "FosterHome": "ERR_FOSTER_HOME_NOT_FOUND",
    "FosterApplication": "ERR_FOSTER_APPLICATION_NOT_FOUND",
    "FosterPlacement": "ERR_FOSTER_PLACEMENT_NOT_FOUND",
    "MedicalRecord": "ERR_MEDICAL_RESOURCE_NOT_FOUND",
    "HealthCertificate": "ERR_MEDICAL_RESOURCE_NOT_FOUND",
    "TransportRun": "ERR_TRANSPORT_RESOURCE_NOT_FOUND",
    "TransportLeg": "ERR_TRANSPORT_RESOURCE_NOT_FOUND",
    "ManifestEntry": "ERR_TRANSPORT_RESOURCE_NOT_FOUND",
    "AdoptionApplication": "ERR_ADOPTION_RESOURCE_NOT_FOUND",
    "Adoption": "ERR_ADOPTION_RESOURCE_NOT_FOUND",
    "OutcomeRecord": "ERR_ADOPTION_RESOURCE_NOT_FOUND",
    "Contribution": "ERR_FUNDING_RESOURCE_NOT_FOUND",
    "PartnerCommitment": "ERR_FUNDING_RESOURCE_NOT_FOUND",
}


def not_found(entity):
    return ApiError(NOT_FOUND[entity])
