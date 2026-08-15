"""Error classes carrying the exact error_id / HTTP status from the catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Auth ---
def err_missing_context():
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                    "X-User-ID and X-User-Role headers are required and the role must be a declared role")


def err_forbidden_role():
    return ApiError("ERR_FORBIDDEN_ROLE", 403,
                    "The acting role is not authorized for this endpoint")


def err_ownership():
    return ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                    "The acting party does not own the target resource")


# --- Existence ---
NOT_FOUND = {
    "handler": "ERR_HANDLER_NOT_FOUND",
    "animal": "ERR_ANIMAL_NOT_FOUND",
    "team": "ERR_TEAM_NOT_FOUND",
    "evaluator": "ERR_EVALUATOR_NOT_FOUND",
    "evaluation": "ERR_EVALUATION_NOT_FOUND",
    "certification": "ERR_CERTIFICATION_NOT_FOUND",
    "vaccination": "ERR_VACCINATION_RECORD_NOT_FOUND",
    "facility": "ERR_FACILITY_NOT_FOUND",
    "agreement": "ERR_AGREEMENT_NOT_FOUND",
    "orientation": "ERR_ORIENTATION_NOT_FOUND",
    "policy": "ERR_POLICY_NOT_FOUND",
    "waiver": "ERR_WAIVER_NOT_FOUND",
    "request": "ERR_REQUEST_NOT_FOUND",
    "visit": "ERR_VISIT_NOT_FOUND",
    "incident": "ERR_INCIDENT_NOT_FOUND",
    "hour_credit": "ERR_HOUR_CREDIT_NOT_FOUND",
}


def err_not_found(resource):
    return ApiError(NOT_FOUND[resource], 404, "%s not found" % resource)


# --- Body / schema ---
def err_invalid_request(msg="Invalid request body"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_enum(field, value):
    return ApiError("ERR_INVALID_ENUM_VALUE", 400,
                    "Field '%s' carries a value outside its declared set: %r" % (field, value))


# --- OCC ---
def err_stale_version():
    return ApiError("ERR_STALE_VERSION", 412,
                    "The expected version does not match the resource's current version")


# --- Generic raiser for catalog ids ---
def err(error_id, http_status, message=None):
    return ApiError(error_id, http_status, message or error_id)
