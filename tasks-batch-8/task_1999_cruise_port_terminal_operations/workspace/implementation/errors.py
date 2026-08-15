"""Error types and error-id constants for the Cruise Port Terminal Ops API."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- Error catalog (PRD section 5) ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                    # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                                # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                                # 404
ERR_VESSEL_SCOPE = "ERR_VESSEL_SCOPE"                          # 403
ERR_STALE_VERSION = "ERR_STALE_VERSION"                        # 412
ERR_STALE_INVOICE_VERSION = "ERR_STALE_INVOICE_VERSION"        # 412
ERR_VALIDATION = "ERR_VALIDATION"                              # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"                        # 409
ERR_POSTURE_EMERGENCY = "ERR_POSTURE_EMERGENCY"                # 409
ERR_BERTH_NOT_FIT = "ERR_BERTH_NOT_FIT"                        # 422
ERR_WASTE_BEFORE_PROVISIONING = "ERR_WASTE_BEFORE_PROVISIONING"  # 409
ERR_TURNAROUND_TOO_SHORT = "ERR_TURNAROUND_TOO_SHORT"          # 422
ERR_WINDOW_NOT_CONTAINED = "ERR_WINDOW_NOT_CONTAINED"          # 422
ERR_ADVISORY_WINDOW_INVALID = "ERR_ADVISORY_WINDOW_INVALID"    # 422
ERR_SERVICE_WINDOW_OUTSIDE_BERTH = "ERR_SERVICE_WINDOW_OUTSIDE_BERTH"  # 422
ERR_BERTH_WINDOW_CONFLICT = "ERR_BERTH_WINDOW_CONFLICT"        # 409
ERR_SCREENING_CAPACITY = "ERR_SCREENING_CAPACITY"              # 409
ERR_APRON_CAPACITY = "ERR_APRON_CAPACITY"                      # 409
ERR_QUEUE_WINDOW_FULL = "ERR_QUEUE_WINDOW_FULL"                # 409
ERR_QUEUE_ORDER = "ERR_QUEUE_ORDER"                            # 409
ERR_DUPLICATE_MANIFEST_REF = "ERR_DUPLICATE_MANIFEST_REF"      # 409
ERR_DUPLICATE_TAG = "ERR_DUPLICATE_TAG"                        # 409
ERR_DUPLICATE_CUSTOMS_CASE = "ERR_DUPLICATE_CUSTOMS_CASE"      # 409
ERR_INVOICE_KIND_EXISTS = "ERR_INVOICE_KIND_EXISTS"            # 409
ERR_REQUEUE_LIMIT = "ERR_REQUEUE_LIMIT"                        # 409
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"        # 409
ERR_CONSTRAINED_REQUIRES_HARBORMASTER = "ERR_CONSTRAINED_REQUIRES_HARBORMASTER"  # 403
ERR_UNDERPAYMENT = "ERR_UNDERPAYMENT"                          # 422
ERR_OVERPAYMENT = "ERR_OVERPAYMENT"                            # 422
ERR_CREDIT_EXCEEDS_OUTSTANDING = "ERR_CREDIT_EXCEEDS_OUTSTANDING"  # 422
ERR_MANIFEST_DIRECTION = "ERR_MANIFEST_DIRECTION"              # 422
ERR_OPEN_MISTAGS = "ERR_OPEN_MISTAGS"                          # 409
ERR_CUSTOMS_NOT_CLEARED = "ERR_CUSTOMS_NOT_CLEARED"            # 409
ERR_CUSTOMS_HOLD_ACTIVE = "ERR_CUSTOMS_HOLD_ACTIVE"            # 409
ERR_OPEN_SERVICE_ORDERS = "ERR_OPEN_SERVICE_ORDERS"            # 409


def err(error_id, http_status, message):
    return ApiError(error_id, http_status, message)


def not_found(what="resource"):
    return ApiError(ERR_NOT_FOUND, 404, f"{what} not found")


def invalid(message):
    return ApiError(ERR_VALIDATION, 400, message)


def invalid_state(message):
    return ApiError(ERR_INVALID_STATE, 409, message)
