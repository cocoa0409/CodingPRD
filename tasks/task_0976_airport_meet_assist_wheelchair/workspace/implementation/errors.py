"""Error classes and error ID constants per the SCAFFOLD error catalog."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Error ID constants (from SCAFFOLD §1.6)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_BAD_REQUEST = "ERR_BAD_REQUEST"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_NO_LEGS = "ERR_NO_LEGS"
ERR_PAYMENT_METHOD_REQUIRED = "ERR_PAYMENT_METHOD_REQUIRED"
ERR_TSA_CLEARANCE_REQUIRED = "ERR_TSA_CLEARANCE_REQUIRED"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_REFERENTIAL_INTEGRITY = "ERR_REFERENTIAL_INTEGRITY"
ERR_TEMPORAL_CONFLICT = "ERR_TEMPORAL_CONFLICT"
ERR_NO_ELIGIBLE_AGENT = "ERR_NO_ELIGIBLE_AGENT"
ERR_NO_AVAILABLE_WHEELCHAIR = "ERR_NO_AVAILABLE_WHEELCHAIR"
ERR_INVOICE_STATE = "ERR_INVOICE_STATE"
ERR_ALREADY_IN_SERVICE = "ERR_ALREADY_IN_SERVICE"
ERR_CHAIR_IN_USE = "ERR_CHAIR_IN_USE"
ERR_WCHC_CHAIR_REQUIRED = "ERR_WCHC_CHAIR_REQUIRED"
ERR_POSTURE_RESTRICTED = "ERR_POSTURE_RESTRICTED"


def unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="Role not authorized for this endpoint"):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def bad_request(msg="Malformed request"):
    return ApiError(ERR_BAD_REQUEST, 400, msg)


def stale_version(msg="Stale version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def invalid_state(msg="Invalid state for this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def no_legs(msg="AssistRequest has no ServiceLegs"):
    return ApiError(ERR_NO_LEGS, 409, msg)


def payment_method_required(msg="Payment method missing"):
    return ApiError(ERR_PAYMENT_METHOD_REQUIRED, 402, msg)


def tsa_clearance_required(msg="TSA clearance required"):
    return ApiError(ERR_TSA_CLEARANCE_REQUIRED, 409, msg)


def segregation_of_duties(msg="Segregation of duties violation"):
    return ApiError(ERR_SEGREGATION_OF_DUTIES, 409, msg)


def referential_integrity(msg="Referential integrity violation"):
    return ApiError(ERR_REFERENTIAL_INTEGRITY, 422, msg)


def temporal_conflict(msg="Temporal conflict"):
    return ApiError(ERR_TEMPORAL_CONFLICT, 409, msg)


def no_eligible_agent(msg="No eligible agent"):
    return ApiError(ERR_NO_ELIGIBLE_AGENT, 409, msg)


def no_available_wheelchair(msg="No available wheelchair"):
    return ApiError(ERR_NO_AVAILABLE_WHEELCHAIR, 409, msg)


def invoice_state(msg="Invoice state violation"):
    return ApiError(ERR_INVOICE_STATE, 409, msg)


def already_in_service(msg="Request already in service"):
    return ApiError(ERR_ALREADY_IN_SERVICE, 409, msg)


def chair_in_use(msg="Chair is in use"):
    return ApiError(ERR_CHAIR_IN_USE, 409, msg)


def wchc_chair_required(msg="WCHC-rated chair required"):
    return ApiError(ERR_WCHC_CHAIR_REQUIRED, 409, msg)


def posture_restricted(msg="Operation restricted under current posture"):
    return ApiError(ERR_POSTURE_RESTRICTED, 409, msg)
