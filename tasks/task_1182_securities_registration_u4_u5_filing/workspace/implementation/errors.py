"""Error classes and error-ID constructors (IDs/HTTP statuses from the error catalog)."""


class ApiError(Exception):
    def __init__(self, error_id, message, status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.status = status


def err_unauthenticated(msg="Missing or unrecognized X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_forbidden_role(msg="Authenticated role is not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN_ROLE", msg, 403)


def err_not_found(msg="Path id or body foreign key references a non-existent entity"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_duplicate(msg="Uniqueness constraint violated"):
    return ApiError("ERR_DUPLICATE", msg, 409)


def err_invalid_state(msg="Entity status does not permit the requested transition"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_stale_version(msg="Expected version does not match the current version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def err_sod(msg="The acting officer is the same user who submitted/filed the target under review"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", msg, 403)


def err_regulatory_gate(msg="Approval blocked: exam, fingerprint, or disclosure precondition unmet"):
    return ApiError("ERR_REGULATORY_GATE", msg, 422)


def err_invalid_request(msg="Malformed field: missing required field, bad enum, or length/pattern violation"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_temporal(msg="Future-dated event/termination, exam result outside its window, or response past due"):
    return ApiError("ERR_TEMPORAL_VIOLATION", msg, 422)


def err_referential(msg="Cross-entity referential rule violated"):
    return ApiError("ERR_REFERENTIAL_VIOLATION", msg, 422)


def err_fiscal(msg="Renewal invoice fiscal rule violated"):
    return ApiError("ERR_FISCAL_VIOLATION", msg, 422)
