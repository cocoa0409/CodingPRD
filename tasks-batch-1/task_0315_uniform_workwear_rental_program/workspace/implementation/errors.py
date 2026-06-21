"""Error catalog and the ApiError exception type.

Every error_id and HTTP status is taken verbatim from PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Validation / auth (PRD §2.9 ordering + §5 catalogue)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"               # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"                 # 403
ERR_RESOURCE_NOT_FOUND = "ERR_RESOURCE_NOT_FOUND"         # 404
ERR_FK_INTEGRITY = "ERR_FK_INTEGRITY"                     # 422
ERR_INVALID_STATE = "ERR_INVALID_STATE"                   # 409
ERR_ACCOUNT_ON_HOLD = "ERR_ACCOUNT_ON_HOLD"              # 409
ERR_WEARER_NOT_ACTIVE = "ERR_WEARER_NOT_ACTIVE"          # 409
ERR_WEARER_HAS_GARMENTS = "ERR_WEARER_HAS_GARMENTS"      # 409
ERR_STOP_WINDOW_OVERLAP = "ERR_STOP_WINDOW_OVERLAP"      # 409
ERR_STOP_SEQUENCE_CONFLICT = "ERR_STOP_SEQUENCE_CONFLICT"  # 409
ERR_WASH_STATION_FULL = "ERR_WASH_STATION_FULL"          # 409
ERR_DUPLICATE_KEY = "ERR_DUPLICATE_KEY"                  # 409
ERR_STALE_VISIT_VERSION = "ERR_STALE_VISIT_VERSION"      # 412
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"              # 400
ERR_SOIL_COUNT_NEGATIVE = "ERR_SOIL_COUNT_NEGATIVE"      # 400
ERR_VISIT_GARMENTS_NOT_CLEAN = "ERR_VISIT_GARMENTS_NOT_CLEAN"  # 409
ERR_CHARGE_ALREADY_SETTLED = "ERR_CHARGE_ALREADY_SETTLED"  # 409
ERR_PAGINATION_INVALID = "ERR_PAGINATION_INVALID"        # 400
ERR_EMBLEM_TEXT_INVALID = "ERR_EMBLEM_TEXT_INVALID"      # 400


def unauthenticated(msg="Missing or invalid X-User-Role header."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Acting role is not permitted for this operation."):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_found(msg="A path id references a non-existent resource."):
    return ApiError(ERR_RESOURCE_NOT_FOUND, 404, msg)


def fk_integrity(msg="A body foreign key does not resolve or crosses accounts."):
    return ApiError(ERR_FK_INTEGRITY, 422, msg)


def invalid_state(msg="Requested transition is not defined from the current state."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def account_on_hold(msg="Footprint-growing operation attempted on an ON_HOLD account."):
    return ApiError(ERR_ACCOUNT_ON_HOLD, 409, msg)


def wearer_not_active(msg="Assignment attempted to a non-ACTIVE wearer."):
    return ApiError(ERR_WEARER_NOT_ACTIVE, 409, msg)


def wearer_has_garments(msg="Remove attempted on a wearer that still holds garments."):
    return ApiError(ERR_WEARER_HAS_GARMENTS, 409, msg)


def stop_window_overlap(msg="New stop window overlaps an existing stop on this route."):
    return ApiError(ERR_STOP_WINDOW_OVERLAP, 409, msg)


def stop_sequence_conflict(msg="stop_sequence duplicated or sequence buffer violated."):
    return ApiError(ERR_STOP_SEQUENCE_CONFLICT, 409, msg)


def wash_station_full(msg="Wash station capacity would be exceeded at some instant."):
    return ApiError(ERR_WASH_STATION_FULL, 409, msg)


def duplicate_key(msg="A unique natural key is already in use."):
    return ApiError(ERR_DUPLICATE_KEY, 409, msg)


def stale_visit_version(msg="expected_service_visit_version does not match current version."):
    return ApiError(ERR_STALE_VISIT_VERSION, 412, msg)


def invalid_request(msg="Request body is not well-formed."):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def soil_count_negative(msg="actual_soil_count must be non-negative."):
    return ApiError(ERR_SOIL_COUNT_NEGATIVE, 400, msg)


def visit_garments_not_clean(msg="One or more garments are still IN_SOIL or IN_WASH."):
    return ApiError(ERR_VISIT_GARMENTS_NOT_CLEAN, 409, msg)


def charge_already_settled(msg="Charge is already paid."):
    return ApiError(ERR_CHARGE_ALREADY_SETTLED, 409, msg)


def pagination_invalid(msg="limit/offset outside the allowed bounds."):
    return ApiError(ERR_PAGINATION_INVALID, 400, msg)


def emblem_text_invalid(msg="emblem_text must not be blank."):
    return ApiError(ERR_EMBLEM_TEXT_INVALID, 400, msg)
