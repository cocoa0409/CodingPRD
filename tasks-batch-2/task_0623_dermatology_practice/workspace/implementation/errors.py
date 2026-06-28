"""Error catalogue (PRD Section 5 / scaffold §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- auth ---
def missing_auth():
    return ApiError("ERR_MISSING_AUTH_CONTEXT", 401, "Missing or malformed auth context")


def forbidden_role():
    return ApiError("ERR_FORBIDDEN_ROLE", 403, "Role not permitted for this operation")


# --- not found (resource-specific) ---
_NOT_FOUND = {
    "patient": "ERR_PATIENT_NOT_FOUND",
    "provider": "ERR_PROVIDER_NOT_FOUND",
    "room": "ERR_ROOM_NOT_FOUND",
    "encounter": "ERR_ENCOUNTER_NOT_FOUND",
    "biopsy": "ERR_BIOPSY_NOT_FOUND",
    "booking": "ERR_BOOKING_NOT_FOUND",
    "prior_auth": "ERR_PA_NOT_FOUND",
    "membership": "ERR_MEMBERSHIP_NOT_FOUND",
    "treatment": "ERR_TREATMENT_NOT_FOUND",
    "charge": "ERR_CHARGE_NOT_FOUND",
    "recall": "ERR_RECALL_NOT_FOUND",
}


def not_found(resource):
    return ApiError(_NOT_FOUND[resource], 404, f"{resource} not found")


# --- input validation ---
def invalid_request(message="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", 422, message)


def invalid_biopsy_result():
    return ApiError("ERR_INVALID_BIOPSY_RESULT", 422, "Invalid biopsy result")


def invalid_interval():
    return ApiError("ERR_INVALID_INTERVAL", 422, "end_at must be strictly after start_at")


def allowed_amount_required():
    return ApiError("ERR_ALLOWED_AMOUNT_REQUIRED", 422, "Allowed-amount requirement violated")


# --- OCC ---
def stale_membership_version():
    return ApiError("ERR_STALE_MEMBERSHIP_VERSION", 412, "Stale membership version")


def stale_room_version():
    return ApiError("ERR_STALE_ROOM_VERSION", 412, "Stale room version")


# --- state ---
def bad_state(error_id):
    return ApiError(error_id, 409, error_id)


# --- business ---
def mohs_requires_suite():
    return ApiError("ERR_MOHS_REQUIRES_MOHS_SUITE", 422, "MOHS requires a MOHS_SUITE room")


def provider_not_mohs():
    return ApiError("ERR_PROVIDER_NOT_MOHS_CREDENTIALED", 422, "Provider not Mohs-credentialed")


def room_interval_conflict():
    return ApiError("ERR_ROOM_INTERVAL_CONFLICT", 409, "Room interval conflict")


def provider_double_booked():
    return ApiError("ERR_PROVIDER_DOUBLE_BOOKED", 409, "Provider double-booked")


def open_biopsy_blocks_close():
    return ApiError("ERR_OPEN_BIOPSY_BLOCKS_CLOSE", 409, "Open biopsy blocks clinical close")


def pa_not_approved():
    return ApiError("ERR_PA_NOT_APPROVED", 422, "PriorAuthorization not approved")


def step_therapy_not_met():
    return ApiError("ERR_STEP_THERAPY_NOT_MET", 422, "Step therapy not met")


def encounter_billing_locked():
    return ApiError("ERR_ENCOUNTER_BILLING_LOCKED", 409, "Encounter billing locked")


def membership_not_active():
    return ApiError("ERR_MEMBERSHIP_NOT_ACTIVE", 409, "Membership not active or encounter not cosmetic")
