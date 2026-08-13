"""Error catalog. Error IDs and HTTP statuses are read from SCAFFOLD.yaml errors table."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def unauthorized(msg="Role lacks permission for the endpoint, or ownership check fails"):
    return ApiError("ERR_UNAUTHORIZED", 403, msg)


def not_found(msg="Path id or body FK does not resolve"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_state(msg="Requested transition not defined from the entity's current state"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def invalid_request(msg="Missing required field, bad type, out-of-range value, or enum outside declared set"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def temporal_invalid(msg="Temporal rule violated"):
    return ApiError("ERR_TEMPORAL_INVALID", 422, msg)


def cross_entity_mismatch(msg="Referenced entities do not belong to the declared parent chain"):
    return ApiError("ERR_CROSS_ENTITY_MISMATCH", 422, msg)


def rep_double_booked(msg="New assignment interval overlaps an existing assignment of the same rep"):
    return ApiError("ERR_REP_DOUBLE_BOOKED", 409, msg)


def duplicate_store(msg="Same (project_id, store_id) already exists in a non-DROPPED ProjectStore row"):
    return ApiError("ERR_DUPLICATE_STORE", 409, msg)


def fixtures_not_delivered(msg="FIXTURE_INSTALL project: departure or check-in blocked by undelivered shipment"):
    return ApiError("ERR_FIXTURES_NOT_DELIVERED", 409, msg)


def billing_model_unresolvable(msg="Billing model cannot be resolved or required rate missing"):
    return ApiError("ERR_BILLING_MODEL_UNRESOLVABLE", 422, msg)


def open_exceptions(msg="Invoice finalize blocked while exceptions remain OPEN"):
    return ApiError("ERR_OPEN_EXCEPTIONS", 409, msg)


def classification_forbidden(msg="C1099 rep assigned to a FIXTURE_INSTALL project"):
    return ApiError("ERR_CLASSIFICATION_FORBIDDEN", 422, msg)


def stale_project_version(msg="expected_project_version does not match project.version"):
    return ApiError("ERR_STALE_PROJECT_VERSION", 412, msg)


def stale_invoice_version(msg="expected_invoice_version does not match invoice.version"):
    return ApiError("ERR_STALE_INVOICE_VERSION", 412, msg)


def rework_not_authorized(msg="Rework assignment requires an APPROVED authorization and REWORK_REQUIRED store"):
    return ApiError("ERR_REWORK_NOT_AUTHORIZED", 409, msg)


def duplicate_invoice(msg="An OPEN or FINALIZED invoice already exists for the project"):
    return ApiError("ERR_DUPLICATE_INVOICE", 409, msg)


def posture_escalated(msg="Client self-approval blocked while project posture is ESCALATED"):
    return ApiError("ERR_POSTURE_ESCALATED", 409, msg)
