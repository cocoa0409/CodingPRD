"""Error classes and error-ID constants for the Cable/Satellite TV Subscription API.

Every error_id and HTTP status is taken verbatim from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    """An API-level error carrying a machine-readable error_id and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---- Error catalog (PRD §5) ------------------------------------------------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"              # 403
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"      # 403
ERR_ACCOUNT_NOT_FOUND = "ERR_ACCOUNT_NOT_FOUND"        # 404
ERR_CATALOG_ENTITY_NOT_FOUND = "ERR_CATALOG_ENTITY_NOT_FOUND"  # 404
ERR_SUBRESOURCE_NOT_FOUND = "ERR_SUBRESOURCE_NOT_FOUND"  # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"                # 409
ERR_ACCOUNT_NOT_ACTIVE = "ERR_ACCOUNT_NOT_ACTIVE"      # 409
ERR_STALE_ACCOUNT_VERSION = "ERR_STALE_ACCOUNT_VERSION"  # 412
ERR_INVALID_VISIT_WINDOW = "ERR_INVALID_VISIT_WINDOW"  # 422
ERR_TECHNICIAN_DOUBLE_BOOKED = "ERR_TECHNICIAN_DOUBLE_BOOKED"  # 409
ERR_ACCOUNT_VISIT_CONFLICT = "ERR_ACCOUNT_VISIT_CONFLICT"  # 409
ERR_ADDON_RANK_TOO_HIGH = "ERR_ADDON_RANK_TOO_HIGH"    # 422
ERR_PROMO_RANK_NOT_MET = "ERR_PROMO_RANK_NOT_MET"      # 422
ERR_PROMO_NOT_WINBACK_ELIGIBLE = "ERR_PROMO_NOT_WINBACK_ELIGIBLE"  # 422
ERR_PROMO_ALREADY_ACTIVE = "ERR_PROMO_ALREADY_ACTIVE"  # 409
ERR_SAME_OR_INVALID_TIER = "ERR_SAME_OR_INVALID_TIER"  # 422
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"            # 422
ERR_INVALID_PRORATION = "ERR_INVALID_PRORATION"        # 422
ERR_DUPLICATE_STATEMENT_CYCLE = "ERR_DUPLICATE_STATEMENT_CYCLE"  # 409
ERR_VALIDATION = "ERR_VALIDATION"                      # 422


def unauthenticated(msg="Missing or malformed authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg="Acting role is not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_resource_owner(msg="Caller does not own this resource"):
    return ApiError(ERR_NOT_RESOURCE_OWNER, 403, msg)


def account_not_found(msg="Account not found"):
    return ApiError(ERR_ACCOUNT_NOT_FOUND, 404, msg)


def catalog_not_found(msg="Referenced catalog entity not found or inactive"):
    return ApiError(ERR_CATALOG_ENTITY_NOT_FOUND, 404, msg)


def subresource_not_found(msg="Sub-resource not found under account"):
    return ApiError(ERR_SUBRESOURCE_NOT_FOUND, 404, msg)


def invalid_state(msg="Requested transition not allowed from current state"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def account_not_active(msg="Account lifecycle_status is not ACTIVE"):
    return ApiError(ERR_ACCOUNT_NOT_ACTIVE, 409, msg)


def stale_version(msg="expected_account_version does not match current version"):
    return ApiError(ERR_STALE_ACCOUNT_VERSION, 412, msg)


def invalid_visit_window(msg="Invalid visit window"):
    return ApiError(ERR_INVALID_VISIT_WINDOW, 422, msg)


def technician_double_booked(msg="Technician already booked for an overlapping window"):
    return ApiError(ERR_TECHNICIAN_DOUBLE_BOOKED, 409, msg)


def account_visit_conflict(msg="Visit conflicts with another visit on this account"):
    return ApiError(ERR_ACCOUNT_VISIT_CONFLICT, 409, msg)


def addon_rank_too_high(msg="Premium channel min_package_rank exceeds current package rank"):
    return ApiError(ERR_ADDON_RANK_TOO_HIGH, 422, msg)


def promo_rank_not_met(msg="Current package rank below PromotionOffer.requires_min_rank"):
    return ApiError(ERR_PROMO_RANK_NOT_MET, 422, msg)


def promo_not_winback_eligible(msg="Offer is not win-back eligible after rollback"):
    return ApiError(ERR_PROMO_NOT_WINBACK_ELIGIBLE, 422, msg)


def promo_already_active(msg="An ACTIVE promotion application already exists"):
    return ApiError(ERR_PROMO_ALREADY_ACTIVE, 409, msg)


def same_or_invalid_tier(msg="Target tier equals current rank or is inactive"):
    return ApiError(ERR_SAME_OR_INVALID_TIER, 422, msg)


def invalid_request(msg="Missing or ill-typed required body field"):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def invalid_proration(msg="active_days outside 0..days_in_cycle"):
    return ApiError(ERR_INVALID_PRORATION, 422, msg)


def duplicate_statement_cycle(msg="A statement for this cycle is already ISSUED"):
    return ApiError(ERR_DUPLICATE_STATEMENT_CYCLE, 409, msg)


def validation(msg="Body validation failed"):
    return ApiError(ERR_VALIDATION, 422, msg)
