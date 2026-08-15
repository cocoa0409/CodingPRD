"""Error classes and error ID constants from the scaffold error catalog (§1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"  # 400
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                    # 400
ERR_UNAUTHORIZED_ROLE = "ERR_UNAUTHORIZED_ROLE"                # 403
ERR_FORBIDDEN_ORG_OWNERSHIP = "ERR_FORBIDDEN_ORG_OWNERSHIP"    # 403
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"        # 403
ERR_ORGANIZATION_NOT_FOUND = "ERR_ORGANIZATION_NOT_FOUND"      # 404
ERR_FACILITY_NOT_FOUND = "ERR_FACILITY_NOT_FOUND"              # 404
ERR_FEE_SCHEDULE_NOT_FOUND = "ERR_FEE_SCHEDULE_NOT_FOUND"      # 404
ERR_WINDOW_NOT_FOUND = "ERR_WINDOW_NOT_FOUND"                  # 404
ERR_APPLICATION_NOT_FOUND = "ERR_APPLICATION_NOT_FOUND"        # 404
ERR_PERMIT_NOT_FOUND = "ERR_PERMIT_NOT_FOUND"                  # 404
ERR_CLOSURE_NOT_FOUND = "ERR_CLOSURE_NOT_FOUND"                # 404
ERR_INVOICE_NOT_FOUND = "ERR_INVOICE_NOT_FOUND"                # 404
ERR_PAYMENT_NOT_FOUND = "ERR_PAYMENT_NOT_FOUND"                # 404
ERR_STRIKE_NOT_FOUND = "ERR_STRIKE_NOT_FOUND"                  # 404
ERR_STALE_VERSION = "ERR_STALE_VERSION"                        # 412
ERR_INVALID_PERMIT_STATE = "ERR_INVALID_PERMIT_STATE"          # 409
ERR_INVALID_APPLICATION_STATE = "ERR_INVALID_APPLICATION_STATE"  # 409
ERR_INVALID_WINDOW_STATE = "ERR_INVALID_WINDOW_STATE"          # 409
ERR_INVALID_INVOICE_STATE = "ERR_INVALID_INVOICE_STATE"        # 409
ERR_INVALID_CLOSURE_STATE = "ERR_INVALID_CLOSURE_STATE"        # 409
ERR_INVALID_SCHEDULE_STATE = "ERR_INVALID_SCHEDULE_STATE"      # 409
ERR_INVALID_PAYMENT_STATE = "ERR_INVALID_PAYMENT_STATE"        # 409
ERR_INVALID_STRIKE_STATE = "ERR_INVALID_STRIKE_STATE"          # 409
ERR_ORG_SUSPENDED = "ERR_ORG_SUSPENDED"                        # 409
ERR_FACILITY_CLOSED = "ERR_FACILITY_CLOSED"                    # 409
ERR_HEADCOUNT_EXCEEDS_CAPACITY = "ERR_HEADCOUNT_EXCEEDS_CAPACITY"  # 409
ERR_WINDOW_NOT_OPEN = "ERR_WINDOW_NOT_OPEN"                    # 409
ERR_WINDOW_NOT_YET_OPEN = "ERR_WINDOW_NOT_YET_OPEN"            # 409
ERR_SLOT_IN_PAST = "ERR_SLOT_IN_PAST"                          # 409
ERR_RESCHEDULE_HORIZON_EXCEEDED = "ERR_RESCHEDULE_HORIZON_EXCEEDED"  # 409
ERR_NO_SHOW_NOT_YET = "ERR_NO_SHOW_NOT_YET"                    # 409
ERR_CHECKIN_WINDOW_CLOSED = "ERR_CHECKIN_WINDOW_CLOSED"        # 409
ERR_CHECKIN_REQUIRED = "ERR_CHECKIN_REQUIRED"                  # 409
ERR_INVALID_TIME_RANGE = "ERR_INVALID_TIME_RANGE"              # 409
ERR_SLOT_OVERLAP = "ERR_SLOT_OVERLAP"                          # 409
ERR_LIGHTS_BUFFER_OVERLAP = "ERR_LIGHTS_BUFFER_OVERLAP"        # 409
ERR_PRIME_CAP_EXCEEDED = "ERR_PRIME_CAP_EXCEEDED"              # 409
ERR_TURF_REST_CAP_EXCEEDED = "ERR_TURF_REST_CAP_EXCEEDED"      # 409
ERR_RESCHEDULE_LIMIT_REACHED = "ERR_RESCHEDULE_LIMIT_REACHED"  # 409
ERR_DEPOSIT_NOT_PAID = "ERR_DEPOSIT_NOT_PAID"                  # 422
ERR_PAYMENT_EXCEEDS_BALANCE = "ERR_PAYMENT_EXCEEDS_BALANCE"    # 422
ERR_REFUND_EXCEEDS_PAID = "ERR_REFUND_EXCEEDS_PAID"            # 422
ERR_INVOICE_HAS_PAYMENTS = "ERR_INVOICE_HAS_PAYMENTS"          # 422


def api_error(error_id, message, http_status):
    return ApiError(error_id, message, http_status)


def missing_user_context(message="Missing or empty X-User-ID / X-User-Role header"):
    return ApiError(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, message, 400)


def invalid_request(message="Malformed body, missing required field, invalid enum, or out-of-range integer"):
    return ApiError(ERR_INVALID_REQUEST, message, 400)


def unauthorized_role(message="Role not permitted to call this endpoint"):
    return ApiError(ERR_UNAUTHORIZED_ROLE, message, 403)


def forbidden_org(message="X-User-ID does not match the resource's organization_id"):
    return ApiError(ERR_FORBIDDEN_ORG_OWNERSHIP, message, 403)


def stale_version(message="expected version does not match the entity's current version"):
    return ApiError(ERR_STALE_VERSION, message, 412)
