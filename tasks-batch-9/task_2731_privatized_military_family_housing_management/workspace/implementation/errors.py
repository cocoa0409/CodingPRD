"""Error catalogue (PRD section 5) and the ApiError exception."""

# error_id -> http status
ERROR_STATUS = {
    # rungs 1-4
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_REQUEST": 400,
    # rungs 5-15 (existence)
    "ERR_INSTALLATION_NOT_FOUND": 404,
    "ERR_HOUSING_UNIT_NOT_FOUND": 404,
    "ERR_SERVICE_MEMBER_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_LEASE_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_WORK_ORDER_NOT_FOUND": 404,
    "ERR_HAZARD_CASE_NOT_FOUND": 404,
    "ERR_LODGING_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    # rungs 16-18 (optimistic concurrency)
    "ERR_STALE_LEASE_VERSION": 412,
    "ERR_STALE_APPLICATION_VERSION": 412,
    "ERR_STALE_ACCOUNT_VERSION": 412,
    # rungs 19-31 (state / safety)
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_TERMINAL_STATE_LOCKED": 409,
    "ERR_OFFER_WINDOW_CLOSED": 409,
    "ERR_APPLICATION_NOT_ACCEPTED": 409,
    "ERR_UNIT_NOT_AVAILABLE": 409,
    "ERR_INSPECTION_NOT_ACKNOWLEDGED": 409,
    "ERR_LEASE_NOT_OCCUPIED": 409,
    "ERR_HAZARD_NOT_ASSESSED": 409,
    "ERR_ALLOTMENT_NOT_ACTIVE": 409,
    "ERR_REOPEN_LIMIT_REACHED": 409,
    "ERR_HAZARD_HOLD_ACTIVE": 409,
    "ERR_UNRESOLVED_CRITICAL_DEFICIENCY": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # rungs 32-39 (referential / constraint)
    "ERR_LEASE_UNIT_MISMATCH": 422,
    "ERR_WORK_ORDER_UNIT_MISMATCH": 422,
    "ERR_ORDERS_NOT_ON_FILE": 422,
    "ERR_NOT_ELIGIBLE_FAMILY_HOUSING": 422,
    "ERR_DUPLICATE_ACTIVE_APPLICATION": 422,
    "ERR_BEDROOM_MISMATCH": 422,
    "ERR_RANK_CATEGORY_MISMATCH": 422,
    "ERR_OCCUPANTS_EXCEED_AUTHORIZED": 422,
    # rungs 40-46 (temporal / fiscal)
    "ERR_LODGING_INTERVAL_OVERLAP": 409,
    "ERR_UNIT_TURN_BUFFER_VIOLATION": 409,
    "ERR_NOTICE_PERIOD_TOO_SHORT": 422,
    "ERR_ESCALATION_NOT_DUE": 409,
    "ERR_PERIOD_ALREADY_POSTED": 409,
    "ERR_BAH_RATE_NOT_ON_FILE": 422,
    "ERR_REINVESTMENT_BALANCE_INSUFFICIENT": 422,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Authentication headers missing or role unknown.",
    "ERR_UNAUTHORIZED_ROLE": "Role is not authorized for this operation.",
    "ERR_NOT_RESOURCE_OWNER": "Caller does not own the addressed resource.",
    "ERR_INVALID_REQUEST": "Request is malformed or contains an invalid value.",
    "ERR_INSTALLATION_NOT_FOUND": "Installation not found.",
    "ERR_HOUSING_UNIT_NOT_FOUND": "Housing unit not found.",
    "ERR_SERVICE_MEMBER_NOT_FOUND": "Service member not found.",
    "ERR_APPLICATION_NOT_FOUND": "Waitlist application not found.",
    "ERR_LEASE_NOT_FOUND": "Lease not found.",
    "ERR_INSPECTION_NOT_FOUND": "Move-in inspection not found.",
    "ERR_WORK_ORDER_NOT_FOUND": "Work order not found.",
    "ERR_HAZARD_CASE_NOT_FOUND": "Hazard case not found.",
    "ERR_LODGING_NOT_FOUND": "Displacement lodging not found.",
    "ERR_DISPUTE_NOT_FOUND": "Dispute case not found.",
    "ERR_ACCOUNT_NOT_FOUND": "Reinvestment account not found.",
    "ERR_STALE_LEASE_VERSION": "Supplied lease version does not match the stored version.",
    "ERR_STALE_APPLICATION_VERSION": "Supplied application version does not match the stored version.",
    "ERR_STALE_ACCOUNT_VERSION": "Supplied account version does not match the stored version.",
    "ERR_INVALID_STATE_TRANSITION": "Requested transition is not declared for the current state.",
    "ERR_TERMINAL_STATE_LOCKED": "Resource is in a terminal state and accepts no further transitions.",
    "ERR_OFFER_WINDOW_CLOSED": "The offer response window has closed.",
    "ERR_APPLICATION_NOT_ACCEPTED": "Application is not in ACCEPTED status.",
    "ERR_UNIT_NOT_AVAILABLE": "Housing unit is not available for this operation.",
    "ERR_INSPECTION_NOT_ACKNOWLEDGED": "No move-in inspection has been acknowledged by the tenant.",
    "ERR_LEASE_NOT_OCCUPIED": "Lease occupancy status does not permit this operation.",
    "ERR_HAZARD_NOT_ASSESSED": "Hazard case has not been assessed.",
    "ERR_ALLOTMENT_NOT_ACTIVE": "Lease allotment is not active.",
    "ERR_REOPEN_LIMIT_REACHED": "Reopen budget for this actor has been exhausted.",
    "ERR_HAZARD_HOLD_ACTIVE": "Housing unit is under a hazard hold.",
    "ERR_UNRESOLVED_CRITICAL_DEFICIENCY": "Inspection still carries unresolved critical deficiencies.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties prevents the same operator from performing both steps.",
    "ERR_LEASE_UNIT_MISMATCH": "Lease does not belong to the named housing unit.",
    "ERR_WORK_ORDER_UNIT_MISMATCH": "Referenced work order does not belong to the named housing unit.",
    "ERR_ORDERS_NOT_ON_FILE": "Required orders reference is not on file.",
    "ERR_NOT_ELIGIBLE_FAMILY_HOUSING": "Service member is not eligible for family housing.",
    "ERR_DUPLICATE_ACTIVE_APPLICATION": "An active application already exists for this member and installation.",
    "ERR_BEDROOM_MISMATCH": "Bedroom eligibility does not match the unit bedroom count.",
    "ERR_RANK_CATEGORY_MISMATCH": "Rank category does not match the unit designation.",
    "ERR_OCCUPANTS_EXCEED_AUTHORIZED": "Occupant count exceeds the authorized household size.",
    "ERR_LODGING_INTERVAL_OVERLAP": "Lodging interval overlaps an existing interval on this lease.",
    "ERR_UNIT_TURN_BUFFER_VIOLATION": "Lease start date violates the unit turn buffer.",
    "ERR_NOTICE_PERIOD_TOO_SHORT": "Termination notice period is too short.",
    "ERR_ESCALATION_NOT_DUE": "Escalation is not yet due.",
    "ERR_PERIOD_ALREADY_POSTED": "Metrics for this period have already been posted.",
    "ERR_BAH_RATE_NOT_ON_FILE": "No BAH rate is on file for the required selector.",
    "ERR_REINVESTMENT_BALANCE_INSUFFICIENT": "Reinvestment account balance is insufficient.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGE.get(error_id, error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
