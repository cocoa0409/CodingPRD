"""Error catalog: error IDs and HTTP statuses from SCAFFOLD.yaml table 1.6."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- 400 ---
def err_missing_user_context(msg="X-User-ID or X-User-Role header missing, malformed, or role not declared"):
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400, msg)


def err_invalid_request(msg="Malformed or inconsistent request body"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


# --- 403 ---
def err_forbidden(msg="Caller role is not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN_FOR_ROLE", 403, msg)


def err_scope(msg="AccountHolder caller does not own the target resource"):
    return ApiError("ERR_ACCOUNT_SCOPE_VIOLATION", 403, msg)


# --- 404 ---
def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


# --- 409 ---
def err_invalid_state(msg="Target resource is not in a valid from-state for this transition"):
    return ApiError("ERR_INVALID_STATE_TRANSITION", 409, msg)


def err_agreement_not_active(msg="Linked license agreement is not ACTIVE"):
    return ApiError("ERR_AGREEMENT_NOT_ACTIVE", 409, msg)


def err_account_suspended(msg="Account is SUSPENDED; new commitments are blocked"):
    return ApiError("ERR_ACCOUNT_SUSPENDED", 409, msg)


def err_credit_hold(msg="Account credit standing is HOLD"):
    return ApiError("ERR_ACCOUNT_CREDIT_HOLD", 409, msg)


def err_event_not_scheduled(msg="Event is not SCHEDULED"):
    return ApiError("ERR_EVENT_NOT_SCHEDULED", 409, msg)


def err_season_locked(msg="Season is SETTLED; season-scoped writes are locked"):
    return ApiError("ERR_SEASON_LOCKED", 409, msg)


def err_cutoff(msg="Catering cutoff has passed"):
    return ApiError("ERR_CATERING_CUTOFF_PASSED", 409, msg)


def err_renewal_window(msg="Clock is outside the renewal window"):
    return ApiError("ERR_RENEWAL_WINDOW_CLOSED", 409, msg)


def err_hold_expired(msg="Rental hold has expired"):
    return ApiError("ERR_HOLD_EXPIRED", 409, msg)


def err_hold_not_expired(msg="Rental hold has not yet expired"):
    return ApiError("ERR_HOLD_NOT_EXPIRED", 409, msg)


def err_credential_window(msg="Clock is outside the credential activation window"):
    return ApiError("ERR_CREDENTIAL_WINDOW", 409, msg)


def err_suite_not_available(msg="Suite is not available for this request"):
    return ApiError("ERR_SUITE_NOT_AVAILABLE", 409, msg)


def err_suite_already_licensed(msg="Suite already has an agreement covering overlapping seasons"):
    return ApiError("ERR_SUITE_ALREADY_LICENSED", 409, msg)


def err_suite_licensed(msg="Suite is LICENSED; it cannot be taken out of service"):
    return ApiError("ERR_SUITE_LICENSED", 409, msg)


def err_event_overlap(msg="Event interval overlaps another SCHEDULED event at the venue"):
    return ApiError("ERR_EVENT_OVERLAP", 409, msg)


def err_credential_capacity(msg="Credential capacity reached for this event and suite"):
    return ApiError("ERR_CREDENTIAL_CAPACITY_EXCEEDED", 409, msg)


def err_duplicate_guest(msg="guest_email already holds a live credential for this event and suite"):
    return ApiError("ERR_DUPLICATE_GUEST", 409, msg)


def err_waitlist_duplicate(msg="A non-terminal waitlist entry already exists for this account, tier and season"):
    return ApiError("ERR_WAITLIST_DUPLICATE", 409, msg)


def err_not_next_in_line(msg="Entry is not the top-ranked eligible WAITING entry"):
    return ApiError("ERR_NOT_NEXT_IN_LINE", 409, msg)


def err_suite_offer_pending(msg="Another waitlist entry is already OFFERED against this suite"):
    return ApiError("ERR_SUITE_OFFER_PENDING", 409, msg)


def err_transfer_pending(msg="Another transfer for this agreement is already in flight"):
    return ApiError("ERR_TRANSFER_ALREADY_PENDING", 409, msg)


def err_transfer_target(msg="Transfer target account is not eligible"):
    return ApiError("ERR_TRANSFER_TARGET_INELIGIBLE", 409, msg)


def err_invoice_has_payments(msg="Invoice has payments in INITIATED or CLEARED allocating to it"):
    return ApiError("ERR_INVOICE_HAS_PAYMENTS", 409, msg)


def err_rental_settlement(msg="Rental invoice must be settled before cancellation"):
    return ApiError("ERR_RENTAL_SETTLEMENT_REQUIRED", 409, msg)


def err_unsettled_balance(msg="Open or past-due invoices block this operation"):
    return ApiError("ERR_UNSETTLED_BALANCE", 409, msg)


def err_no_licensed_suites(msg="Venue has no LICENSED suites"):
    return ApiError("ERR_NO_LICENSED_SUITES", 409, msg)


# --- 412 ---
def err_stale_version(msg="Expected version does not match the resource's current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


# --- 422 ---
def err_allocation_exceeds(msg="Allocation exceeds the invoice's amount due"):
    return ApiError("ERR_ALLOCATION_EXCEEDS_DUE", 422, msg)


def err_allocation_mismatch(msg="Allocated invoice does not belong to the payment's account"):
    return ApiError("ERR_ALLOCATION_ACCOUNT_MISMATCH", 422, msg)
