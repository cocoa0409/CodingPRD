"""Error catalogue (SCAFFOLD errors / PRD 5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_STATION_OWNERSHIP_MISMATCH": 403,
    "ERR_STATION_NOT_FOUND": 404,
    "ERR_FUNDING_AGREEMENT_NOT_FOUND": 404,
    "ERR_PRESSURE_VESSEL_NOT_FOUND": 404,
    "ERR_PRODUCTION_ASSET_NOT_FOUND": 404,
    "ERR_PRODUCTION_LOT_NOT_FOUND": 404,
    "ERR_DELIVERY_NOT_FOUND": 404,
    "ERR_DISPENSE_SESSION_NOT_FOUND": 404,
    "ERR_SAFETY_EVENT_NOT_FOUND": 404,
    "ERR_INCENTIVE_CLAIM_NOT_FOUND": 404,
    "ERR_UPTIME_REPORT_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_STATION_VERSION": 412,
    "ERR_STALE_AGREEMENT_VERSION": 412,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_STATION_FROZEN": 409,
    "ERR_POSTURE_RESTRICTS_H70": 422,
    "ERR_RESPONDER_TRAINING_LAPSED": 422,
    "ERR_VESSEL_INSPECTION_OVERDUE": 422,
    "ERR_LOT_NOT_RELEASED": 422,
    "ERR_QA_NOT_PASSED": 422,
    "ERR_SAMPLE_BEFORE_PRODUCTION_END": 422,
    "ERR_FILL_PROTOCOL_VIOLATION": 422,
    "ERR_ARRIVAL_OUTSIDE_WINDOW": 422,
    "ERR_OFFLOAD_BAY_CONFLICT": 409,
    "ERR_POWER_CONTRACT_OVERLAP": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_NO_POWER_CONTRACT": 422,
    "ERR_LOT_CI_NOT_CERTIFIED": 422,
    "ERR_LOT_NOT_DELIVERED_IN_PERIOD": 422,
    "ERR_STATION_CODE_TAKEN": 409,
    "ERR_CODE_TAKEN": 409,
    "ERR_LOT_CODE_TAKEN": 409,
    "ERR_CLAIM_PERIOD_OVERLAP": 409,
    "ERR_REPORT_PERIOD_OVERLAP": 409,
    "ERR_AGREEMENT_MISMATCH": 409,
    "ERR_NO_NOZZLE_AVAILABLE": 409,
    "ERR_METERED_EXCEEDS_PLANNED": 422,
    "ERR_PRESSURE_CLASS_UNSUPPORTED": 422,
    "ERR_VESSEL_PRESSURE_LIMIT": 422,
    "ERR_COMPRESSOR_OFFLINE": 422,
    "ERR_RESCHEDULE_LIMIT_REACHED": 409,
    "ERR_CASCADE_INSUFFICIENT": 422,
    "ERR_INSUFFICIENT_AVAILABLE_INVENTORY": 422,
    "ERR_STORAGE_CAPACITY_EXCEEDED": 422,
    "ERR_NO_CREDITS_TO_ISSUE": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and X-User-Role must name a known role.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not permitted to call this endpoint.",
    "ERR_STATION_OWNERSHIP_MISMATCH": "The acting StationOperator does not own the targeted station resource.",
    "ERR_STATION_NOT_FOUND": "Station not found.",
    "ERR_FUNDING_AGREEMENT_NOT_FOUND": "Funding agreement not found.",
    "ERR_PRESSURE_VESSEL_NOT_FOUND": "Pressure vessel not found.",
    "ERR_PRODUCTION_ASSET_NOT_FOUND": "Production asset not found.",
    "ERR_PRODUCTION_LOT_NOT_FOUND": "Production lot not found.",
    "ERR_DELIVERY_NOT_FOUND": "Delivery not found.",
    "ERR_DISPENSE_SESSION_NOT_FOUND": "Dispense session not found.",
    "ERR_SAFETY_EVENT_NOT_FOUND": "Safety event not found.",
    "ERR_INCENTIVE_CLAIM_NOT_FOUND": "Incentive claim not found.",
    "ERR_UPTIME_REPORT_NOT_FOUND": "Uptime report not found.",
    "ERR_INVALID_REQUEST": "The request failed schema validation.",
    "ERR_STALE_STATION_VERSION": "expected_station_version does not match the station's current version.",
    "ERR_STALE_AGREEMENT_VERSION": "expected_funding_agreement_version does not match the agreement's current version.",
    "ERR_INVALID_STATE_TRANSITION": "The resource's current state does not declare the requested transition.",
    "ERR_STATION_FROZEN": "The station's safety posture is FROZEN.",
    "ERR_POSTURE_RESTRICTS_H70": "A RESTRICTED station cannot serve an H70 fill.",
    "ERR_RESPONDER_TRAINING_LAPSED": "The station has fewer than two current EMERGENCY_RESPONSE certifications.",
    "ERR_VESSEL_INSPECTION_OVERDUE": "The pressure vessel's inspection status is OVERDUE or CONDEMNED.",
    "ERR_LOT_NOT_RELEASED": "The delivery's production lot is not RELEASED.",
    "ERR_QA_NOT_PASSED": "The lot's quality and carbon-intensity branches are not both complete.",
    "ERR_SAMPLE_BEFORE_PRODUCTION_END": "sampled_at precedes the lot's production_end_at.",
    "ERR_FILL_PROTOCOL_VIOLATION": "precool_temp_achieved_c is warmer than required_precool_c.",
    "ERR_ARRIVAL_OUTSIDE_WINDOW": "Arrival recorded outside the booked window.",
    "ERR_OFFLOAD_BAY_CONFLICT": "All offload bays are booked for an intersecting window.",
    "ERR_POWER_CONTRACT_OVERLAP": "The power contract interval falls inside the changeover buffer of an existing contract.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting user already performed the incompatible preceding step.",
    "ERR_NO_POWER_CONTRACT": "No power supply contract covers the lot's production_end_at.",
    "ERR_LOT_CI_NOT_CERTIFIED": "A referenced production lot has ci_status other than CERTIFIED.",
    "ERR_LOT_NOT_DELIVERED_IN_PERIOD": "A claimed lot has no ACCEPTED delivery to this station inside the claim period.",
    "ERR_STATION_CODE_TAKEN": "Station code already exists.",
    "ERR_CODE_TAKEN": "Code already exists.",
    "ERR_LOT_CODE_TAKEN": "Lot code already exists.",
    "ERR_CLAIM_PERIOD_OVERLAP": "Another non-DENIED claim for this station and program covers an intersecting period.",
    "ERR_REPORT_PERIOD_OVERLAP": "Another FINAL uptime report for this station covers an intersecting period.",
    "ERR_AGREEMENT_MISMATCH": "Cross-aggregate ownership mismatch.",
    "ERR_NO_NOZZLE_AVAILABLE": "Every nozzle is occupied by an in-flight session.",
    "ERR_METERED_EXCEEDS_PLANNED": "metered_kg exceeds the session's planned_kg.",
    "ERR_PRESSURE_CLASS_UNSUPPORTED": "The station does not support the requested pressure class.",
    "ERR_VESSEL_PRESSURE_LIMIT": "The offload would push the receiving vessel above its mawp_bar.",
    "ERR_COMPRESSOR_OFFLINE": "Compressor makeup is required but the compressor is OFFLINE.",
    "ERR_RESCHEDULE_LIMIT_REACHED": "The delivery has reached the reschedule limit.",
    "ERR_CASCADE_INSUFFICIENT": "The cascade cannot serve planned_kg without breaching a vessel's min_residual_bar.",
    "ERR_INSUFFICIENT_AVAILABLE_INVENTORY": "planned_kg exceeds the station's available_kg.",
    "ERR_STORAGE_CAPACITY_EXCEEDED": "The offload would exceed the station's storage capacity.",
    "ERR_NO_CREDITS_TO_ISSUE": "The claim nets no credits.",
}


def api_error(error_id, message=None):
    return ApiError(error_id, ERROR_STATUS[error_id], message)


def raise_error(error_id, message=None):
    raise api_error(error_id, message)
