"""Error class carrying error_id, message, and http_status (from the scaffold's
error catalog / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- auth / existence ---
def err_missing_auth():
    return ApiError("ERR_MISSING_AUTH", 401,
                    "X-User-ID or X-User-Role header missing or malformed.")


def err_invalid_role():
    return ApiError("ERR_INVALID_ROLE", 401, "X-User-Role is not a recognized role.")


def err_forbidden():
    return ApiError("ERR_FORBIDDEN", 403,
                    "Role is not permitted to perform this operation.")


def err_not_resource_owner():
    return ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                    "Owner may only act on resources they own.")


def err_not_found():
    return ApiError("ERR_NOT_FOUND", 404, "A path-referenced resource does not exist.")


# --- request validation ---
def err_invalid_request(msg=None):
    return ApiError("ERR_INVALID_REQUEST", 422,
                    msg or "Request body is malformed.")


def err_cross_facility():
    return ApiError("ERR_CROSS_FACILITY_REFERENCE", 409,
                    "A body foreign key belongs to a different facility.")


# --- state ---
def err_invalid_state():
    return ApiError("ERR_INVALID_STATE", 409,
                    "Target resource is not in a state from which this transition is defined.")


# --- vaccination / temperament ---
def err_vaccination_required():
    return ApiError("ERR_VACCINATION_REQUIRED", 409,
                    "Pet vaccination_status is not VALID at the current date.")


def err_temperament_not_cleared():
    return ApiError("ERR_TEMPERAMENT_NOT_CLEARED", 409,
                    "Pet temperament_clearance is FLAGGED.")


# --- run / capacity / grouping ---
def err_run_not_eligible():
    return ApiError("ERR_RUN_NOT_ELIGIBLE", 409,
                    "Run is not eligible for this assignment.")


def err_run_overlap():
    return ApiError("ERR_RUN_OVERLAP", 409,
                    "Overnight suite interval overlaps an existing assignment.")


def err_run_capacity_exceeded():
    return ApiError("ERR_RUN_CAPACITY_EXCEEDED", 409,
                    "Daycare pen capacity would be exceeded on that date.")


def err_group_incompatible():
    return ApiError("ERR_GROUP_INCOMPATIBLE", 409,
                    "Group compatibility score exceeds the applicable ceiling.")


def err_pet_double_booked():
    return ApiError("ERR_PET_DOUBLE_BOOKED", 409,
                    "Assignment window overlaps another assignment for the same pet.")


def err_no_run_assigned():
    return ApiError("ERR_NO_RUN_ASSIGNED", 409,
                    "Confirm attempted with no HELD RunAssignment.")


# --- fiscal / package ---
def err_deposit_unpaid():
    return ApiError("ERR_DEPOSIT_UNPAID", 409,
                    "deposit_paid_cents is less than deposit_cents.")


def err_package_not_redeemable():
    return ApiError("ERR_PACKAGE_NOT_REDEEMABLE", 409,
                    "Package is not redeemable for this reservation.")


def err_renewal_not_allowed():
    return ApiError("ERR_RENEWAL_NOT_ALLOWED", 409,
                    "Package auto_renew is false.")


# --- lifecycle timing / blocking ---
def err_checkin_too_early():
    return ApiError("ERR_CHECKIN_TOO_EARLY", 409,
                    "check_in attempted before start_date.")


def err_no_show_too_early():
    return ApiError("ERR_NO_SHOW_TOO_EARLY", 409,
                    "mark_no_show attempted before the service date has passed.")


def err_addon_out_of_window():
    return ApiError("ERR_ADDON_OUT_OF_WINDOW", 409,
                    "AddOn scheduled_date is outside the reservation window.")


def err_belongings_outstanding():
    return ApiError("ERR_BELONGINGS_OUTSTANDING", 409,
                    "A belongings entry has not been returned.")


# --- concurrency ---
def err_stale_version():
    return ApiError("ERR_STALE_VERSION", 412,
                    "expected_reservation_version does not match the live version.")
