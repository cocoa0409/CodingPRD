"""Error catalogue (PRD section 5)."""

ERROR_STATUS = {
    # authentication / authorisation
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_MOVEMENT_CARRIER": 403,
    "ERR_NOT_BOND_SURETY": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    # existence
    "ERR_CARRIER_NOT_FOUND": 404,
    "ERR_BOND_NOT_FOUND": 404,
    "ERR_PORT_NOT_FOUND": 404,
    "ERR_MOVEMENT_NOT_FOUND": 404,
    "ERR_HOLD_NOT_FOUND": 404,
    "ERR_AMENDMENT_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_PETITION_NOT_FOUND": 404,
    "ERR_RESOURCE_NOT_FOUND": 404,
    # uniqueness
    "ERR_DUPLICATE_IRS_NUMBER": 409,
    "ERR_DUPLICATE_PORT_CODE": 409,
    # optimistic concurrency
    "ERR_STALE_MOVEMENT_VERSION": 412,
    "ERR_STALE_CLAIM_VERSION": 412,
    # own-entity state
    "ERR_MOVEMENT_INVALID_STATE": 409,
    "ERR_HOLD_INVALID_STATE": 409,
    "ERR_AMENDMENT_INVALID_STATE": 409,
    "ERR_REPORT_INVALID_STATE": 409,
    "ERR_CLAIM_INVALID_STATE": 409,
    "ERR_PETITION_INVALID_STATE": 409,
    "ERR_BOND_INVALID_STATE": 409,
    "ERR_CARRIER_INVALID_STATE": 409,
    # cross-entity state
    "ERR_CARRIER_NOT_ACTIVE": 409,
    "ERR_BOND_NOT_ACTIVE": 409,
    "ERR_PREDECESSOR_NOT_ARRIVED": 409,
    "ERR_MOVEMENT_IN_GENERAL_ORDER": 409,
    # cargo safety
    "ERR_SEAL_NOT_APPLIED": 409,
    "ERR_SEAL_INTEGRITY_UNRESOLVED": 409,
    "ERR_HOLD_OPEN": 409,
    "ERR_UNAUTHORIZED_DIVERSION": 422,
    # temporal
    "ERR_TRANSIT_DEADLINE_PASSED": 422,
    "ERR_BOND_COVERAGE_GAP": 422,
    "ERR_EXAM_WINDOW_INVALID": 422,
    "ERR_CLOCK_NOT_MONOTONIC": 422,
    # business constraints
    "ERR_ROUTE_TYPE_MISMATCH": 422,
    "ERR_STB_WINDOW_CONFLICT": 409,
    "ERR_EXAM_CAPACITY_EXCEEDED": 409,
    "ERR_EXTENSION_LIMIT_EXCEEDED": 422,
    "ERR_GRANTED_DAYS_INVALID": 422,
    "ERR_PETITION_ROUND_LIMIT": 422,
    "ERR_HOLD_TYPE_NOT_ALLOWED": 422,
    "ERR_REPORT_TYPE_NOT_ALLOWED": 422,
    "ERR_DUPLICATE_CLAIM": 409,
    "ERR_NO_VIOLATION_TO_CLAIM": 422,
    "ERR_MITIGATION_FACTOR_INVALID": 422,
    # fiscal
    "ERR_BOND_INSUFFICIENT": 422,
    "ERR_NO_ELIGIBLE_BOND": 422,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or invalid.",
    "ERR_UNAUTHORIZED": "The acting role is not authorised for this operation.",
    "ERR_NOT_MOVEMENT_CARRIER": "The acting carrier does not own this movement.",
    "ERR_NOT_BOND_SURETY": "The acting surety does not administer this bond.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties bars this operator from this action.",
    "ERR_INVALID_REQUEST": "The request payload is invalid.",
    "ERR_INVALID_PAGINATION": "Pagination parameters are out of range.",
    "ERR_CARRIER_NOT_FOUND": "No such bonded carrier.",
    "ERR_BOND_NOT_FOUND": "No such customs bond.",
    "ERR_PORT_NOT_FOUND": "No such port.",
    "ERR_MOVEMENT_NOT_FOUND": "No such in-bond movement.",
    "ERR_HOLD_NOT_FOUND": "No such examination hold.",
    "ERR_AMENDMENT_NOT_FOUND": "No such amendment request.",
    "ERR_REPORT_NOT_FOUND": "No such movement report.",
    "ERR_CLAIM_NOT_FOUND": "No such liquidated-damages claim.",
    "ERR_PETITION_NOT_FOUND": "No such mitigation petition.",
    "ERR_RESOURCE_NOT_FOUND": "No such record.",
    "ERR_DUPLICATE_IRS_NUMBER": "That IRS number is already registered.",
    "ERR_DUPLICATE_PORT_CODE": "That port code is already registered.",
    "ERR_STALE_MOVEMENT_VERSION": "The movement version supplied is stale.",
    "ERR_STALE_CLAIM_VERSION": "The claim version supplied is stale.",
    "ERR_MOVEMENT_INVALID_STATE": "The movement's state does not admit this transition.",
    "ERR_HOLD_INVALID_STATE": "The examination hold is not open.",
    "ERR_AMENDMENT_INVALID_STATE": "The amendment request can no longer be decided.",
    "ERR_REPORT_INVALID_STATE": "The report is not pending proof.",
    "ERR_CLAIM_INVALID_STATE": "The claim's status does not admit this action.",
    "ERR_PETITION_INVALID_STATE": "The petition's status does not admit this action.",
    "ERR_BOND_INVALID_STATE": "That bond status transition is not supported.",
    "ERR_CARRIER_INVALID_STATE": "That carrier status transition is not supported.",
    "ERR_CARRIER_NOT_ACTIVE": "The bonded carrier is not active.",
    "ERR_BOND_NOT_ACTIVE": "The underwriting bond is not active.",
    "ERR_PREDECESSOR_NOT_ARRIVED": "The predecessor movement has not arrived.",
    "ERR_MOVEMENT_IN_GENERAL_ORDER": "The movement is in general order.",
    "ERR_SEAL_NOT_APPLIED": "No seal has been applied to this movement.",
    "ERR_SEAL_INTEGRITY_UNRESOLVED": "The seal integrity problem is unresolved.",
    "ERR_HOLD_OPEN": "An examination hold on this movement is still open.",
    "ERR_UNAUTHORIZED_DIVERSION": "Arrival reported at an unauthorised port.",
    "ERR_TRANSIT_DEADLINE_PASSED": "The extension window has closed.",
    "ERR_BOND_COVERAGE_GAP": "The bond does not cover the whole transit.",
    "ERR_EXAM_WINDOW_INVALID": "The examination window is invalid.",
    "ERR_CLOCK_NOT_MONOTONIC": "The logical clock never runs backwards.",
    "ERR_ROUTE_TYPE_MISMATCH": "The route shape contradicts the in-bond type.",
    "ERR_STB_WINDOW_CONFLICT": "The single-transaction bond window collides.",
    "ERR_EXAM_CAPACITY_EXCEEDED": "The port's examination capacity is exhausted.",
    "ERR_EXTENSION_LIMIT_EXCEEDED": "Cumulative extension days would exceed the limit.",
    "ERR_GRANTED_DAYS_INVALID": "The granted days are invalid.",
    "ERR_PETITION_ROUND_LIMIT": "The petition round limit has been reached.",
    "ERR_HOLD_TYPE_NOT_ALLOWED": "That hold type may not be requested directly.",
    "ERR_REPORT_TYPE_NOT_ALLOWED": "That report type is not permitted for this movement.",
    "ERR_DUPLICATE_CLAIM": "A live claim of that type already exists on this movement.",
    "ERR_NO_VIOLATION_TO_CLAIM": "The movement does not exhibit the claimed violation.",
    "ERR_MITIGATION_FACTOR_INVALID": "The mitigation factors are invalid.",
    "ERR_BOND_INSUFFICIENT": "The bond has insufficient available amount.",
    "ERR_NO_ELIGIBLE_BOND": "No eligible bond could underwrite this movement.",
    "ERR_PAYMENT_AMOUNT_MISMATCH": "The paid amount does not equal the amount owed.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
