"""Error types and error-id constants for the Truck Parking Reservation Network."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error id helpers (HTTP statuses pinned by the PRD error catalogue) ---
def unauthenticated(msg="Missing or unknown X-User-Role, or missing X-User-ID"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden(msg="Role not permitted on this endpoint or ownership mismatch"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def validation(msg="Malformed request body"):
    return ApiError("ERR_VALIDATION", 400, msg)


def invalid_state(msg="State machine rejects the transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def stale_version(msg="Expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def site_escalated(msg="Site posture is ESCALATED"):
    return ApiError("ERR_SITE_ESCALATED", 409, msg)


def window_in_past(msg="RESERVED arrival_date is before the clock date"):
    return ApiError("ERR_WINDOW_IN_PAST", 422, msg)


def walkin_not_today(msg="WALK_IN arrival_date differs from the clock date"):
    return ApiError("ERR_WALKIN_NOT_TODAY", 422, msg)


def window_too_long(msg="night_count above 14"):
    return ApiError("ERR_WINDOW_TOO_LONG", 422, msg)


def window_invalid(msg="Unparseable arrival_date, night_count below 1, or bad window"):
    return ApiError("ERR_WINDOW_INVALID", 422, msg)


def checkin_not_open(msg="Check-in attempted before checkin_open_at"):
    return ApiError("ERR_CHECKIN_WINDOW_NOT_OPEN", 409, msg)


def checkin_grace_elapsed(msg="Check-in attempted after the no-show grace boundary"):
    return ApiError("ERR_CHECKIN_GRACE_ELAPSED", 409, msg)


def reopen_window_expired(msg="Incident reopen attempted after resolved_at + 72h"):
    return ApiError("ERR_REOPEN_WINDOW_EXPIRED", 409, msg)


def stall_window_conflict(msg="Requested stall has an overlapping non-terminal booking"):
    return ApiError("ERR_STALL_WINDOW_CONFLICT", 409, msg)


def driver_window_conflict(msg="Driver already holds an overlapping non-terminal booking"):
    return ApiError("ERR_DRIVER_WINDOW_CONFLICT", 409, msg)


def extension_conflict(msg="Extension window not free on the booking's stall"):
    return ApiError("ERR_EXTENSION_CONFLICT", 409, msg)


def driver_suspended(msg="Driver standing is SUSPENDED"):
    return ApiError("ERR_DRIVER_SUSPENDED", 409, msg)


def driver_not_authorized(msg="No ACTIVE DriverAuthorization for the (driver, fleet) pair"):
    return ApiError("ERR_DRIVER_NOT_AUTHORIZED", 403, msg)


def fleet_suspended(msg="FleetAccount is not ACTIVE"):
    return ApiError("ERR_FLEET_SUSPENDED", 409, msg)


def site_capacity_full(msg="No eligible stall for the requested pool/class/window"):
    return ApiError("ERR_SITE_CAPACITY_FULL", 409, msg)


def amenity_capacity_exceeded(msg="Capacitated amenity would exceed nightly_capacity"):
    return ApiError("ERR_AMENITY_CAPACITY_EXCEEDED", 409, msg)


def duplicate_waitlist_entry(msg="Driver already has a QUEUED or OFFERED entry at this site"):
    return ApiError("ERR_DUPLICATE_WAITLIST_ENTRY", 409, msg)


def duplicate_stall_number(msg="stall_number already exists at this site"):
    return ApiError("ERR_DUPLICATE_STALL_NUMBER", 409, msg)


def stall_not_reservable(msg="Explicit stall_id mismatches pool/class/site, or product foreign/discontinued"):
    return ApiError("ERR_STALL_NOT_RESERVABLE", 409, msg)


def stall_out_of_service(msg="Assigned stall is OUT_OF_SERVICE"):
    return ApiError("ERR_STALL_OUT_OF_SERVICE", 409, msg)


def offer_expired(msg="Waitlist accept after offer_expires_at"):
    return ApiError("ERR_OFFER_EXPIRED", 409, msg)


def segregation_of_duties(msg="Incident resolver must differ from the acknowledger"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


def fleet_credit_exceeded(msg="Projected exposure would exceed the fleet credit limit"):
    return ApiError("ERR_FLEET_CREDIT_EXCEEDED", 422, msg)


def spend_cap_exceeded(msg="Per-night quote average exceeds the authorization spend cap"):
    return ApiError("ERR_SPEND_CAP_EXCEEDED", 422, msg)


def overpayment(msg="Payment amount exceeds the remaining balance due"):
    return ApiError("ERR_OVERPAYMENT", 422, msg)


def payment_not_due(msg="Payment attempted with nothing due"):
    return ApiError("ERR_PAYMENT_NOT_DUE", 409, msg)


def invoice_not_payable(msg="Invoice is not in a payable status"):
    return ApiError("ERR_INVOICE_NOT_PAYABLE", 409, msg)
