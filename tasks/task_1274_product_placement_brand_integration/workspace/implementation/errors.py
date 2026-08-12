"""Error classes and error-id constants from the SCAFFOLD error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED_ROLE = "ERR_UNAUTHORIZED_ROLE"
ERR_FORBIDDEN_OWNERSHIP = "ERR_FORBIDDEN_OWNERSHIP"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_DISCLOSURE_NOT_ACKNOWLEDGED = "ERR_DISCLOSURE_NOT_ACKNOWLEDGED"
ERR_INVALID_SCENE_WINDOW = "ERR_INVALID_SCENE_WINDOW"
ERR_SCENE_WINDOW_OVERLAP = "ERR_SCENE_WINDOW_OVERLAP"
ERR_OPPORTUNITY_UNAVAILABLE = "ERR_OPPORTUNITY_UNAVAILABLE"
ERR_CATEGORY_EXCLUSIVITY_CONFLICT = "ERR_CATEGORY_EXCLUSIVITY_CONFLICT"
ERR_AIRDATE_PROXIMITY_CONFLICT = "ERR_AIRDATE_PROXIMITY_CONFLICT"
ERR_EPISODE_ALREADY_AIRED = "ERR_EPISODE_ALREADY_AIRED"
ERR_EPISODE_NOT_LOCKED = "ERR_EPISODE_NOT_LOCKED"
ERR_EPISODE_NOT_AIRED = "ERR_EPISODE_NOT_AIRED"
ERR_AIR_DATE_NOT_REACHED = "ERR_AIR_DATE_NOT_REACHED"
ERR_BRAND_SUSPENDED = "ERR_BRAND_SUSPENDED"
ERR_BRIEF_NOT_OPEN = "ERR_BRIEF_NOT_OPEN"
ERR_BUDGET_EXCEEDED = "ERR_BUDGET_EXCEEDED"
ERR_FEE_BELOW_MINIMUM = "ERR_FEE_BELOW_MINIMUM"
ERR_CLEARANCE_REQUIRED = "ERR_CLEARANCE_REQUIRED"
ERR_SHIPMENT_CONTRACT_MISMATCH = "ERR_SHIPMENT_CONTRACT_MISMATCH"


def unauthenticated(msg="Missing or unknown X-User-Role / X-User-ID headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized_role(msg="Role not permitted for this endpoint"):
    return ApiError(ERR_UNAUTHORIZED_ROLE, 403, msg)


def forbidden_ownership(msg="Entity-backed role acting on a resource it does not own"):
    return ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, msg)


def invalid_request(msg="Malformed body"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def not_found(msg="Resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_state(msg="Target entity not in a valid from-state for the requested transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def already_terminal(msg="Operation attempted on an entity in a terminal state"):
    return ApiError(ERR_ALREADY_TERMINAL, 409, msg)


def stale_version(msg="expected version does not match the current version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def segregation_of_duties(msg="Same operator attempting both sides of a segregated duty"):
    return ApiError(ERR_SEGREGATION_OF_DUTIES, 403, msg)


def disclosure_not_acknowledged(msg="Verification requires an ACKNOWLEDGED disclosure filing for the contract"):
    return ApiError(ERR_DISCLOSURE_NOT_ACKNOWLEDGED, 422, msg)
