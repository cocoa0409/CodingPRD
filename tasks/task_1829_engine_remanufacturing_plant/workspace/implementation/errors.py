"""Error catalogue (PRD section 5) and the exception used to raise them."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP[error_id]
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_VALIDATION = "ERR_VALIDATION"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_FORBIDDEN_OWNERSHIP = "ERR_FORBIDDEN_OWNERSHIP"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_DISTRIBUTOR_CREDIT_HOLD = "ERR_DISTRIBUTOR_CREDIT_HOLD"
ERR_SPEC_NOT_ACTIVE = "ERR_SPEC_NOT_ACTIVE"
ERR_CORE_RETURN_NOT_GRADED = "ERR_CORE_RETURN_NOT_GRADED"
ERR_DEPOSIT_NOT_LINKABLE = "ERR_DEPOSIT_NOT_LINKABLE"
ERR_COMPONENT_QUARANTINED = "ERR_COMPONENT_QUARANTINED"
ERR_EMISSIONS_TIER_MISMATCH = "ERR_EMISSIONS_TIER_MISMATCH"
ERR_DYNO_NOT_PASSED = "ERR_DYNO_NOT_PASSED"
ERR_SEALER_IS_TESTER = "ERR_SEALER_IS_TESTER"
ERR_ADJUDICATOR_IS_TEARDOWN_TECH = "ERR_ADJUDICATOR_IS_TEARDOWN_TECH"
ERR_WARRANTY_EXPIRED = "ERR_WARRANTY_EXPIRED"
ERR_STATION_SCHEDULE_OVERLAP = "ERR_STATION_SCHEDULE_OVERLAP"
ERR_DYNO_CELL_SCHEDULE_OVERLAP = "ERR_DYNO_CELL_SCHEDULE_OVERLAP"
ERR_ROUTE_SEQUENCE_VIOLATION = "ERR_ROUTE_SEQUENCE_VIOLATION"
ERR_OPERATIONS_INCOMPLETE = "ERR_OPERATIONS_INCOMPLETE"
ERR_NO_ELIGIBLE_ENGINE = "ERR_NO_ELIGIBLE_ENGINE"
ERR_REUSE_GRADE_INSUFFICIENT = "ERR_REUSE_GRADE_INSUFFICIENT"
ERR_INTERCHANGE_INCOMPATIBLE = "ERR_INTERCHANGE_INCOMPATIBLE"
ERR_CREDIT_LIMIT_EXCEEDED = "ERR_CREDIT_LIMIT_EXCEEDED"
ERR_STALE_VERSION = "ERR_STALE_VERSION"

ERROR_HTTP = {
    ERR_UNAUTHENTICATED: 401,
    ERR_FORBIDDEN_ROLE: 403,
    ERR_VALIDATION: 400,
    ERR_NOT_FOUND: 404,
    ERR_FORBIDDEN_OWNERSHIP: 403,
    ERR_INVALID_STATE: 409,
    ERR_DISTRIBUTOR_CREDIT_HOLD: 409,
    ERR_SPEC_NOT_ACTIVE: 409,
    ERR_CORE_RETURN_NOT_GRADED: 409,
    ERR_DEPOSIT_NOT_LINKABLE: 422,
    ERR_COMPONENT_QUARANTINED: 422,
    ERR_EMISSIONS_TIER_MISMATCH: 422,
    ERR_DYNO_NOT_PASSED: 422,
    ERR_SEALER_IS_TESTER: 403,
    ERR_ADJUDICATOR_IS_TEARDOWN_TECH: 403,
    ERR_WARRANTY_EXPIRED: 422,
    ERR_STATION_SCHEDULE_OVERLAP: 409,
    ERR_DYNO_CELL_SCHEDULE_OVERLAP: 409,
    ERR_ROUTE_SEQUENCE_VIOLATION: 422,
    ERR_OPERATIONS_INCOMPLETE: 422,
    ERR_NO_ELIGIBLE_ENGINE: 422,
    ERR_REUSE_GRADE_INSUFFICIENT: 422,
    ERR_INTERCHANGE_INCOMPATIBLE: 422,
    ERR_CREDIT_LIMIT_EXCEEDED: 422,
    ERR_STALE_VERSION: 412,
}

DEFAULT_MESSAGES = {
    ERR_UNAUTHENTICATED: "X-User-Role and X-User-ID headers are required and the role must be a declared role.",
    ERR_FORBIDDEN_ROLE: "The caller role is not authorized for this endpoint.",
    ERR_VALIDATION: "The request body is malformed or fails field validation.",
    ERR_NOT_FOUND: "A referenced resource does not exist.",
    ERR_FORBIDDEN_OWNERSHIP: "A distributor-role caller may act only on its own resources.",
    ERR_INVALID_STATE: "The target entity is not in a state that allows the requested transition.",
    ERR_DISTRIBUTOR_CREDIT_HOLD: "The buyer distributor is on CREDIT_HOLD.",
    ERR_SPEC_NOT_ACTIVE: "The build spec is not ACTIVE.",
    ERR_CORE_RETURN_NOT_GRADED: "The core return is not GRADED/CLOSED with a rebuildable grade.",
    ERR_DEPOSIT_NOT_LINKABLE: "core_deposit_id is not a HELD deposit owned by the returning distributor.",
    ERR_COMPONENT_QUARANTINED: "The component is QUARANTINED.",
    ERR_EMISSIONS_TIER_MISMATCH: "A CALIFORNIA-requirement distributor may only buy CALIFORNIA-tier engines.",
    ERR_DYNO_NOT_PASSED: "The engine's latest dyno result is not PASS.",
    ERR_SEALER_IS_TESTER: "The sealing inspector must differ from the technician who recorded the latest dyno test.",
    ERR_ADJUDICATOR_IS_TEARDOWN_TECH: "The adjudicator must differ from the technician who performed the teardown.",
    ERR_WARRANTY_EXPIRED: "The claim is filed at or after 360 days since the engine was sold.",
    ERR_STATION_SCHEDULE_OVERLAP: "Another operation holds an overlapping window on the same station.",
    ERR_DYNO_CELL_SCHEDULE_OVERLAP: "Another dyno test holds a buffer-extended overlapping window on the same cell.",
    ERR_ROUTE_SEQUENCE_VIOLATION: "An operation with a smaller sequence is not COMPLETED.",
    ERR_OPERATIONS_INCOMPLETE: "Advancing to ASSEMBLY requires every operation to be COMPLETED.",
    ERR_NO_ELIGIBLE_ENGINE: "No SEALED engine of the requested build spec is available.",
    ERR_REUSE_GRADE_INSUFFICIENT: "The component reuse grade is null or not allowed by the spec.",
    ERR_INTERCHANGE_INCOMPATIBLE: "The component interchange group is not allowed by the spec.",
    ERR_CREDIT_LIMIT_EXCEEDED: "deposits_held_cents plus the new deposit would exceed the credit limit.",
    ERR_STALE_VERSION: "The supplied expected version does not match the current version.",
}


def raise_error(error_id, message=None):
    raise ApiError(error_id, message)
