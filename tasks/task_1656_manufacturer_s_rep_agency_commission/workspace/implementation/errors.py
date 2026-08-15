"""Error types and the complete error catalog (id -> http status)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog — id: (http_status, default message)
CATALOG = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": (400, "Missing or invalid user context headers"),
    "ERR_FORBIDDEN_FOR_ROLE": (403, "Role is not authorized for this endpoint"),
    "ERR_FORBIDDEN_NOT_OWNER": (403, "Caller does not own the target resource"),
    "ERR_NOT_FOUND": (404, "Resource not found"),
    "ERR_INVALID_REQUEST": (400, "Malformed or invalid request body"),
    "ERR_INVALID_STATE_TRANSITION": (409, "State does not permit the requested transition"),
    "ERR_STALE_PRINCIPAL_VERSION": (412, "expected_principal_version does not match current principal version"),
    "ERR_STALE_ORDER_VERSION": (412, "expected_order_version does not match current order version"),
    "ERR_AGREEMENT_NOT_ACTIVE": (409, "The principal has no ACTIVE territory agreement"),
    "ERR_AGREEMENT_CONFLICT": (409, "Another ACTIVE agreement already exists for this principal"),
    "ERR_TERRITORY_NOT_COVERED": (409, "Line territory is outside the ACTIVE agreement's territory_codes"),
    "ERR_NO_ACTIVE_RATE_SCHEDULE": (409, "The principal has no ACTIVE rate schedule"),
    "ERR_UNKNOWN_FAMILY_CODE": (422, "Family code absent from the ACTIVE rate schedule"),
    "ERR_LINE_TERMINATED": (409, "Principal is TERMINATED"),
    "ERR_LINE_UNDER_TERMINATION_NOTICE": (409, "Principal is under a termination notice"),
    "ERR_REP_ON_HOLD": (409, "Rep is on COMMISSION_HOLD"),
    "ERR_PROTECTION_WINDOW_OVERLAP": (409, "Protection window overlaps an existing APPROVED registration"),
    "ERR_CHECKOUT_WINDOW_CONFLICT": (409, "Sample unit is inside a blocked interval"),
    "ERR_RENEWAL_WINDOW_NOT_OPEN": (409, "Renewal window is not open"),
    "ERR_RENEWAL_LIMIT_REACHED": (409, "Renewal limit reached"),
    "ERR_TAIL_PERIOD_EXPIRED": (409, "Invoice is outside the termination tail window"),
    "ERR_FUTURE_DATED": (422, "placed_at is after the current logical clock"),
    "ERR_CLOCK_REGRESSION": (409, "Clock may only move strictly forward"),
    "ERR_SPLIT_SUM_INVALID": (422, "Split rows must cover every line and sum to 10000 bp per line"),
    "ERR_SPLITS_LOCKED": (409, "Splits are locked once the order is no longer ATTRIBUTED"),
    "ERR_DUPLICATE_EXTERNAL_REF": (409, "external_order_ref already used by a non-CANCELLED order of this principal"),
    "ERR_DUPLICATE_PERIOD_LABEL": (409, "period_label already exists for this principal"),
    "ERR_DUPLICATE_SERIAL": (409, "serial_number already registered for this principal"),
    "ERR_TERRITORY_COVERAGE_CONFLICT": (409, "territory_codes overlap another ACTIVE rep"),
    "ERR_RETURN_QTY_EXCEEDS_SHIPPED": (409, "Return quantity exceeds returnable quantity"),
    "ERR_UNRESOLVED_DISPUTES": (409, "Statement has DISPUTED lines"),
    "ERR_LINES_NOT_DISPOSITIONED": (409, "Statement has un-dispositioned lines"),
}


def err(error_id, message=None):
    status, default_msg = CATALOG[error_id]
    return ApiError(error_id, status, message or default_msg)


def not_found(what="Resource"):
    return err("ERR_NOT_FOUND", "%s not found" % what)


def invalid_request(message):
    return err("ERR_INVALID_REQUEST", message)
