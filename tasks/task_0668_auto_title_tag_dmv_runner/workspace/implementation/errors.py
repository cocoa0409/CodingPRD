"""Error classes and error-id constants (PRD §5 / scaffold §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error id constants (exact strings from PRD §5 / scaffold §1.6) ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"                  # 403
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"          # 403
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"    # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                            # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"                    # 409
ERR_NO_CHARGE_TO_REFUND = "ERR_NO_CHARGE_TO_REFUND"        # 409
ERR_DOCUMENTS_INCOMPLETE = "ERR_DOCUMENTS_INCOMPLETE"      # 409
ERR_TRIP_WINDOW_OVERLAP = "ERR_TRIP_WINDOW_OVERLAP"        # 409
ERR_SLA_EXPIRED = "ERR_SLA_EXPIRED"                        # 409
ERR_TRIP_AT_CAPACITY = "ERR_TRIP_AT_CAPACITY"              # 409
ERR_REWORK_LIMIT_REACHED = "ERR_REWORK_LIMIT_REACHED"      # 409
ERR_TRIP_NOT_RETURNED = "ERR_TRIP_NOT_RETURNED"            # 409
ERR_CREDIT_LIMIT_EXCEEDED = "ERR_CREDIT_LIMIT_EXCEEDED"    # 409
ERR_INVALID_TRANSACTION_FIELDS = "ERR_INVALID_TRANSACTION_FIELDS"  # 422
ERR_PAYMENT_AMOUNT_MISMATCH = "ERR_PAYMENT_AMOUNT_MISMATCH"  # 422
ERR_STALE_VERSION = "ERR_STALE_VERSION"                    # 412
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                # 400
ERR_VALIDATION = "ERR_VALIDATION"                          # 422


def unauthenticated(msg="Missing or unrecognized authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg="Acting role is not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_resource_owner(msg="AccountHolder does not own this resource"):
    return ApiError(ERR_NOT_RESOURCE_OWNER, 403, msg)


def segregation_of_duties(msg="Perfecting officer must not be the submitting user"):
    return ApiError(ERR_SEGREGATION_OF_DUTIES, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_state(msg="Resource is not in a state from which this transition is allowed"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def no_charge_to_refund(msg="No CHARGE payment exists to compensate"):
    return ApiError(ERR_NO_CHARGE_TO_REFUND, 409, msg)


def documents_incomplete(msg="Required document checklist is not fully verified"):
    return ApiError(ERR_DOCUMENTS_INCOMPLETE, 409, msg)


def trip_window_overlap(msg="Trip window overlaps an existing non-terminal trip"):
    return ApiError(ERR_TRIP_WINDOW_OVERLAP, 409, msg)


def sla_expired(msg="EXPEDITE SLA window has expired"):
    return ApiError(ERR_SLA_EXPIRED, 409, msg)


def trip_at_capacity(msg="Trip is at capacity"):
    return ApiError(ERR_TRIP_AT_CAPACITY, 409, msg)


def rework_limit_reached(msg="Rework limit reached"):
    return ApiError(ERR_REWORK_LIMIT_REACHED, 409, msg)


def trip_not_returned(msg="Submission's leg trip has not RETURNED"):
    return ApiError(ERR_TRIP_NOT_RETURNED, 409, msg)


def credit_limit_exceeded(msg="Completion would exceed the account credit limit"):
    return ApiError(ERR_CREDIT_LIMIT_EXCEEDED, 409, msg)


def invalid_transaction_fields(msg="Transaction fields invalid for transaction_type"):
    return ApiError(ERR_INVALID_TRANSACTION_FIELDS, 422, msg)


def payment_amount_mismatch(msg="Payment amount does not match settled total"):
    return ApiError(ERR_PAYMENT_AMOUNT_MISMATCH, 422, msg)


def stale_version(msg="expected version does not match current version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def invalid_request(msg="Malformed request body"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def validation(msg="Field fails a typed constraint"):
    return ApiError(ERR_VALIDATION, 422, msg)
