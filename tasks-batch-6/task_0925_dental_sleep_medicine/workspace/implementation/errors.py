"""Error catalogue (PRD section 5) and the ApiError exception."""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_CARE_TEAM": 403,
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_PROVIDER_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_FOUND": 404,
    "ERR_APPLIANCE_NOT_FOUND": 404,
    "ERR_RECORD_NOT_FOUND": 404,
    "ERR_VALIDATION": 400,
    "ERR_INVALID_ENUM": 422,
    "ERR_DUPLICATE_IDENTIFIER": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_RECORDS_FROZEN": 409,
    "ERR_DEVICE_RECALL_HOLD": 409,
    "ERR_PROVIDER_TYPE_MISMATCH": 422,
    "ERR_SELF_REFERRAL": 422,
    "ERR_DIAGNOSIS_REQUIRED": 422,
    "ERR_STUDY_NON_DIAGNOSTIC": 422,
    "ERR_DIAGNOSIS_EXPIRED": 422,
    "ERR_CPAP_TRIAL_REQUIRED": 422,
    "ERR_ACTIVE_APPLIANCE_EXISTS": 409,
    "ERR_TITRATION_INTERVAL": 422,
    "ERR_PROTRUSION_LIMIT_EXCEEDED": 422,
    "ERR_PLATEAU_REQUIRED": 422,
    "ERR_EFFICACY_LOOP_OPEN": 409,
    "ERR_DENTAL_PAYER_ROUTING": 422,
    "ERR_SWO_MISSING": 422,
    "ERR_SWO_AFTER_DELIVERY": 422,
    "ERR_F2F_ENCOUNTER_STALE": 422,
    "ERR_PRIOR_AUTH_REQUIRED": 422,
    "ERR_POD_MISSING": 422,
    "ERR_USEFUL_LIFETIME_NOT_ELAPSED": 422,
    "ERR_REPAIR_NOT_BILLABLE": 422,
    "ERR_ADHERENCE_NOT_MET": 422,
    "ERR_LOANER_UNAVAILABLE": 409,
    "ERR_APPEAL_LIMIT_REACHED": 409,
}


class ApiError(Exception):
    """A rung failure.  Carries the declared error id and its HTTP status."""

    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
