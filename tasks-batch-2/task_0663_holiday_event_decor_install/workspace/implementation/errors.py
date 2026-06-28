"""Error classes and error ID constants."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (§1.6 / PRD §5)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_STALE_CONTRACT_VERSION = "ERR_STALE_CONTRACT_VERSION"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_CONTRACT_TYPE_MISMATCH = "ERR_CONTRACT_TYPE_MISMATCH"
ERR_PROPOSAL_ALREADY_DECIDED = "ERR_PROPOSAL_ALREADY_DECIDED"
ERR_DAMAGE_CONTEXT_INVALID = "ERR_DAMAGE_CONTEXT_INVALID"
ERR_CREW_DOUBLE_BOOKED = "ERR_CREW_DOUBLE_BOOKED"
ERR_BAY_CAPACITY_EXCEEDED = "ERR_BAY_CAPACITY_EXCEEDED"
ERR_CONTRACT_NOT_ACTIVE = "ERR_CONTRACT_NOT_ACTIVE"
ERR_OFFER_EXPIRED = "ERR_OFFER_EXPIRED"
ERR_DUPLICATE_CODE = "ERR_DUPLICATE_CODE"
ERR_VISITS_NOT_COMPLETE = "ERR_VISITS_NOT_COMPLETE"
ERR_WORKORDER_NOT_COMPLETED = "ERR_WORKORDER_NOT_COMPLETED"


def unauthenticated(msg="Missing or invalid authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg="Role not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_resource_owner(msg="Acting client does not own the targeted resource"):
    return ApiError(ERR_NOT_RESOURCE_OWNER, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def reference_not_found(msg="A referenced resource does not exist"):
    return ApiError(ERR_REFERENCE_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid request"):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def stale_contract_version(msg="expected_contract_version does not match current contract version"):
    return ApiError(ERR_STALE_CONTRACT_VERSION, 412, msg)


def invalid_state(msg="Transition not defined from current state"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def contract_type_mismatch(msg="contract_type must equal the client's account_type"):
    return ApiError(ERR_CONTRACT_TYPE_MISMATCH, 422, msg)


def proposal_already_decided(msg="Contract not PROPOSED or a sibling proposal already accepted"):
    return ApiError(ERR_PROPOSAL_ALREADY_DECIDED, 409, msg)


def damage_context_invalid(msg="Parent work order is not a COMPLETED TAKEDOWN"):
    return ApiError(ERR_DAMAGE_CONTEXT_INVALID, 409, msg)


def crew_double_booked(msg="Crew is double-booked within the 1-day buffer"):
    return ApiError(ERR_CREW_DOUBLE_BOOKED, 409, msg)


def bay_capacity_exceeded(msg="Storage lot exceeds bay aggregate capacity over the interval"):
    return ApiError(ERR_BAY_CAPACITY_EXCEEDED, 409, msg)


def contract_not_active(msg="Owning contract is not ACTIVE"):
    return ApiError(ERR_CONTRACT_NOT_ACTIVE, 409, msg)


def offer_expired(msg="Renewal offer has expired"):
    return ApiError(ERR_OFFER_EXPIRED, 409, msg)


def duplicate_code(msg="Code collides with an existing value"):
    return ApiError(ERR_DUPLICATE_CODE, 409, msg)


def visits_not_complete(msg="A visit is still PLANNED"):
    return ApiError(ERR_VISITS_NOT_COMPLETE, 409, msg)


def workorder_not_completed(msg="schedule_status is not COMPLETED"):
    return ApiError(ERR_WORKORDER_NOT_COMPLETED, 409, msg)
