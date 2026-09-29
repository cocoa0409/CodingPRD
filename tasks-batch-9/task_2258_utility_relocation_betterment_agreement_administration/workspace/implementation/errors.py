"""Error catalogue (PRD section 5 / scaffold 1.6)."""

ERROR_HTTP = {
    # authentication and authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_OWNER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_OWNER_NOT_FOUND": 404,
    "ERR_FACILITY_NOT_FOUND": 404,
    "ERR_INVESTIGATION_NOT_FOUND": 404,
    "ERR_CONFLICT_NOT_FOUND": 404,
    "ERR_DETERMINATION_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_SLOT_NOT_FOUND": 404,
    "ERR_COMMITMENT_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_DOCUMENT_NOT_FOUND": 404,
    "ERR_FINDING_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    # state
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_AGREEMENT_NOT_EXECUTABLE": 409,
    "ERR_SETTLEMENT_STATE_INVALID": 409,
    "ERR_COMMITMENT_STATE_INVALID": 409,
    "ERR_PROJECT_CLOSED": 409,
    "ERR_STALE_VERSION": 412,
    # safety and compliance
    "ERR_CLEARANCE_POSTURE_BLOCKED": 409,
    "ERR_OWNER_ON_REIMBURSEMENT_HOLD": 409,
    # referential and dependency
    "ERR_PRIOR_RIGHTS_NOT_ISSUED": 409,
    "ERR_PERMIT_NOT_GRANTED": 409,
    "ERR_DEPENDENCY_NOT_CLEARED": 409,
    "ERR_EXECUTED_AGREEMENT_BLOCKS_SUPERSEDE": 409,
    "ERR_OPEN_AUDIT_FINDING": 409,
    "ERR_NO_ELIGIBLE_COST_DOCUMENTATION": 422,
    # temporal
    "ERR_WINDOW_OUTSIDE_CONSTRUCTION": 422,
    "ERR_FACILITY_WINDOW_CONFLICT": 409,
    "ERR_TRENCH_WINDOW_NOT_CONTAINED": 422,
    # constraint and limits
    "ERR_TRENCH_SLOT_AT_CAPACITY": 409,
    "ERR_REVISION_LIMIT_EXCEEDED": 409,
    "ERR_APPEAL_LIMIT_EXCEEDED": 409,
    # fiscal
    "ERR_NOT_TO_EXCEED_TOO_LOW": 422,
    "ERR_AUTHORITY_EXCEEDED": 409,
    "ERR_DELAY_NOT_COMPENSABLE": 422,
    "ERR_PROJECT_CLOSE_BLOCKED": 409,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Missing or invalid authentication headers.",
    "ERR_UNAUTHORIZED": "The acting role may not invoke this endpoint.",
    "ERR_OWNER_SCOPE_VIOLATION": "The acting utility owner representative may not act on this row.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this actor from performing this action.",
    "ERR_INVALID_REQUEST": "The request payload or query parameters are malformed.",
    "ERR_INVALID_STATE_TRANSITION": "The requested transition is not available from the current state.",
    "ERR_AGREEMENT_NOT_EXECUTABLE": "The agreement's execution status does not permit this action.",
    "ERR_SETTLEMENT_STATE_INVALID": "The agreement's settlement status does not permit this action.",
    "ERR_COMMITMENT_STATE_INVALID": "The schedule commitment is not in a state that permits this action.",
    "ERR_PROJECT_CLOSED": "The owning project is closed.",
    "ERR_STALE_VERSION": "The supplied parent version is stale.",
    "ERR_CLEARANCE_POSTURE_BLOCKED": "The project's clearance posture is FUNDING_BLOCKED.",
    "ERR_OWNER_ON_REIMBURSEMENT_HOLD": "The counterparty utility owner is on reimbursement hold.",
    "ERR_PRIOR_RIGHTS_NOT_ISSUED": "The conflict has no issued prior-rights determination.",
    "ERR_PERMIT_NOT_GRANTED": "Not every permit record of the conflict is granted.",
    "ERR_DEPENDENCY_NOT_CLEARED": "The predecessor conflict is not cleared.",
    "ERR_EXECUTED_AGREEMENT_BLOCKS_SUPERSEDE": "An executed agreement blocks superseding the earlier plan.",
    "ERR_OPEN_AUDIT_FINDING": "The agreement still carries an open audit finding.",
    "ERR_NO_ELIGIBLE_COST_DOCUMENTATION": "No eligible accepted cost documentation exists.",
    "ERR_WINDOW_OUTSIDE_CONSTRUCTION": "The commitment window is outside the project's construction window.",
    "ERR_FACILITY_WINDOW_CONFLICT": "The commitment window collides with another window on the same facility.",
    "ERR_TRENCH_WINDOW_NOT_CONTAINED": "The commitment window is not contained in the joint trench opening.",
    "ERR_TRENCH_SLOT_AT_CAPACITY": "The joint trench slot is at capacity.",
    "ERR_REVISION_LIMIT_EXCEEDED": "The plan revision limit has been reached.",
    "ERR_APPEAL_LIMIT_EXCEEDED": "The appeal limit has been reached.",
    "ERR_NOT_TO_EXCEED_TOO_LOW": "The not-to-exceed ceiling is below the indirect-loaded plan estimate.",
    "ERR_AUTHORITY_EXCEEDED": "The committed reimbursement ledger would exceed the project's authority.",
    "ERR_DELAY_NOT_COMPENSABLE": "The analysed claim has no compensable days.",
    "ERR_PROJECT_CLOSE_BLOCKED": "The project cannot be closed yet.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGE.get(
            error_id, "%s occurred while handling the request." % error_id
        )


def fail(error_id, message=None):
    raise ApiError(error_id, message)
