"""Error catalogue (SCAFFOLD 1.6) and the exception the routes raise."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_CATALOG.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


def api_error(error_id, message=None):
    return ApiError(error_id, message)


ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_FIELD_VALUE": 422,
    "ERR_REFERENCED_ENTITY_NOT_FOUND": 404,
    "ERR_PRACTICE_SCOPE_MISMATCH": 409,
    "ERR_ACTOR_NOT_ASSIGNED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_PERMIT_ALREADY_OPEN": 409,
    "ERR_STALE_BLOCK_VERSION": 412,
    "ERR_STALE_LOT_VERSION": 412,
    "ERR_STALE_CASE_VERSION": 412,
    "ERR_CLOCK_MONOTONIC_VIOLATION": 409,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_CASE_NOT_CLEARED": 409,
    "ERR_LOT_UNAVAILABLE": 409,
    "ERR_SEDATION_PRIVILEGE_UNAVAILABLE": 409,
    "ERR_PERMIT_LEVEL_INSUFFICIENT": 409,
    "ERR_REMEDIATION_WINDOW_EXPIRED": 409,
    "ERR_DRILL_COMPLIANCE_LAPSED": 409,
    "ERR_STAFFING_RATIO_UNMET": 409,
    "ERR_FASTING_REQUIREMENT_UNMET": 409,
    "ERR_ESCORT_REQUIRED": 409,
    "ERR_RISK_BAND_PROHIBITIVE": 409,
    "ERR_CBCT_JUSTIFICATION_INVALID": 422,
    "ERR_PREREQUISITE_CASE_INCOMPLETE": 409,
    "ERR_PREREQUISITE_CYCLE": 409,
    "ERR_REFERRAL_ACKNOWLEDGEMENT_REQUIRED": 409,
    "ERR_REGULATOR_NOTIFICATION_REQUIRED": 409,
    "ERR_CASE_OUTSIDE_BLOCK_WINDOW": 409,
    "ERR_BLOCK_SURGEON_MISMATCH": 409,
    "ERR_ROOM_TURNOVER_CONFLICT": 409,
    "ERR_MONITOR_DOUBLE_BOOKED": 409,
    "ERR_RECOVERY_CAPACITY_EXCEEDED": 409,
    "ERR_BLOCK_CAPACITY_EXCEEDED": 409,
    "ERR_IMPLANT_STOCK_INSUFFICIENT": 409,
    "ERR_NO_ELIGIBLE_IMPLANT_LOT": 409,
    "ERR_CHARGE_TOTAL_MISMATCH": 422,
    "ERR_CONSIGNMENT_CREDIT_LIMIT_EXCEEDED": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-Role is missing or unrecognised, or X-User-ID is missing for an entity-backed role.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role may not perform this operation.",
    "ERR_RESOURCE_NOT_FOUND": "A resource in the request path does not exist.",
    "ERR_INVALID_REQUEST": "The request body is malformed, missing a required field, or carries an unknown field.",
    "ERR_INVALID_FIELD_VALUE": "A supplied value violates its type, enum or range constraint.",
    "ERR_REFERENCED_ENTITY_NOT_FOUND": "A referenced entity does not exist.",
    "ERR_PRACTICE_SCOPE_MISMATCH": "A referenced row belongs to a different practice.",
    "ERR_ACTOR_NOT_ASSIGNED": "The acting staff member is not the one this operation is bound to.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting staff member may not both perform and review this step.",
    "ERR_PERMIT_ALREADY_OPEN": "The practice already holds an open anesthesia permit.",
    "ERR_STALE_BLOCK_VERSION": "expected_block_version does not match the block's current version.",
    "ERR_STALE_LOT_VERSION": "expected_lot_version does not match the lot's current version.",
    "ERR_STALE_CASE_VERSION": "expected_case_version does not match the case's current version.",
    "ERR_CLOCK_MONOTONIC_VIOLATION": "The logical clock may not move backwards.",
    "ERR_INVALID_STATE_TRANSITION": "The requested transition is not declared for the row's current state.",
    "ERR_CASE_NOT_CLEARED": "The case's clearance_status is not CLEARED.",
    "ERR_LOT_UNAVAILABLE": "The implant lot is quarantined.",
    "ERR_SEDATION_PRIVILEGE_UNAVAILABLE": "The practice's sedation privilege does not admit this anesthesia level.",
    "ERR_PERMIT_LEVEL_INSUFFICIENT": "The open permit's level ranks below the level this case requires.",
    "ERR_REMEDIATION_WINDOW_EXPIRED": "The probation remediation window has closed.",
    "ERR_DRILL_COMPLIANCE_LAPSED": "The practice's drill compliance ratio is below 0.75.",
    "ERR_STAFFING_RATIO_UNMET": "The sedation staffing matrix is unsatisfied.",
    "ERR_FASTING_REQUIREMENT_UNMET": "The recorded fasting intervals are insufficient.",
    "ERR_ESCORT_REQUIRED": "A confirmed, named escort is required.",
    "ERR_RISK_BAND_PROHIBITIVE": "The final risk band is PROHIBITIVE.",
    "ERR_CBCT_JUSTIFICATION_INVALID": "The justification code is not allowed for this field of view.",
    "ERR_PREREQUISITE_CASE_INCOMPLETE": "The prerequisite case has not reached COMPLETED.",
    "ERR_PREREQUISITE_CYCLE": "The requested prerequisite link would create a cycle.",
    "ERR_REFERRAL_ACKNOWLEDGEMENT_REQUIRED": "The referring provider's acknowledgement is still outstanding.",
    "ERR_REGULATOR_NOTIFICATION_REQUIRED": "The regulator notification must be recorded before closing this event.",
    "ERR_CASE_OUTSIDE_BLOCK_WINDOW": "The case's planned window is not contained in the block's window.",
    "ERR_BLOCK_SURGEON_MISMATCH": "The case's primary surgeon is not the block's surgeon.",
    "ERR_ROOM_TURNOVER_CONFLICT": "Another committed case in the same room overlaps this window once the turnover buffer is applied.",
    "ERR_MONITOR_DOUBLE_BOOKED": "The monitor is already assigned to an overlapping committed case.",
    "ERR_RECOVERY_CAPACITY_EXCEEDED": "The projected peak recovery occupancy would exceed the practice's recovery bays.",
    "ERR_BLOCK_CAPACITY_EXCEEDED": "The case's duration exceeds the block's remaining open minutes.",
    "ERR_IMPLANT_STOCK_INSUFFICIENT": "The lot cannot satisfy the requested quantity or expires before the case's planned start.",
    "ERR_NO_ELIGIBLE_IMPLANT_LOT": "No eligible implant lot lies inside the sizing tolerance.",
    "ERR_CHARGE_TOTAL_MISMATCH": "The service lines do not sum to the case's total_charge_cents.",
    "ERR_CONSIGNMENT_CREDIT_LIMIT_EXCEEDED": "The reservation would push consignment exposure past the practice's credit limit.",
}
