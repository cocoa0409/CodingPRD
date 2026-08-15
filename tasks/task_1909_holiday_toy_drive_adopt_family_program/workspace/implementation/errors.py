"""Error catalog for the Holiday Toy Drive API."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- Auth ---
def err_unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def err_privacy(msg="Donor-scoped request attempts to read or filter on PII fields"):
    return ApiError("ERR_PRIVACY_VIOLATION", 403, msg)


def err_sod(msg="Segregation of duties violation"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


# --- Existence ---
def err_not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


# --- State / OCC ---
def err_invalid_state(msg="Requested transition is not defined from the resource's current state"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_stale_version(msg="Expected version does not match current row version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def err_invalid_request(msg="Required field missing, wrong type, or enum value outside declared set"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_window(msg="Invalid time window"):
    return ApiError("ERR_INVALID_WINDOW", 422, msg)


# --- Business ---
def err_intake_closed(msg="Intake is not currently open for this campaign"):
    return ApiError("ERR_INTAKE_CLOSED", 409, msg)


def err_agency_suspended(msg="Agency is suspended and may not submit referrals"):
    return ApiError("ERR_AGENCY_SUSPENDED", 409, msg)


def err_quota(msg="Agency referral quota reached"):
    return ApiError("ERR_AGENCY_QUOTA_EXCEEDED", 409, msg)


def err_child_cap(msg="Adding a child would exceed campaign.max_children_per_family"):
    return ApiError("ERR_FAMILY_CHILD_CAP", 409, msg)


def err_child_too_old(msg="Child's computed age at distribution_date >= 19 years"):
    return ApiError("ERR_CHILD_TOO_OLD", 422, msg)


def err_wish_value(msg="Sum of child's active wish items would exceed campaign.max_gift_value_cents"):
    return ApiError("ERR_WISH_VALUE_EXCEEDED", 422, msg)


def err_duplicate(msg="Uniqueness violation"):
    return ApiError("ERR_DUPLICATE", 409, msg)


def err_dup_flag_open(msg="Family has an OPEN DuplicateFlag"):
    return ApiError("ERR_DUPLICATE_FLAG_OPEN", 409, msg)


def err_pledge_expired(msg="Adoption confirm attempted more than 72 hours after pledged_at"):
    return ApiError("ERR_PLEDGE_EXPIRED", 409, msg)


def err_adoption_cap(msg="Donor's concurrent non-terminal adoption count reached max_adoptions_per_season"):
    return ApiError("ERR_ADOPTION_CAP_EXCEEDED", 409, msg)


def err_coverage(msg="Adoption coverage invalid"):
    return ApiError("ERR_ADOPTION_COVERAGE_INVALID", 422, msg)


def err_commitment_low(msg="commitment_cents below campaign minimum at confirm time"):
    return ApiError("ERR_COMMITMENT_TOO_LOW", 422, msg)


def err_deadline_passed(msg="Gift receive attempted after return_deadline + grace hours"):
    return ApiError("ERR_RETURN_DEADLINE_PASSED", 409, msg)


def err_gift_wish_mismatch(msg="gift.wish_item_id belongs to a different child or is not in APPROVED/COMMITTED status"):
    return ApiError("ERR_GIFT_WISH_MISMATCH", 422, msg)


def err_gift_value(msg="gift.declared_value_cents exceeds campaign.max_gift_value_cents"):
    return ApiError("ERR_GIFT_VALUE_EXCEEDED", 422, msg)


def err_slot_overlap(msg="Two slots for the same family have overlapping half-open windows"):
    return ApiError("ERR_SLOT_OVERLAP", 409, msg)


def err_lane_capacity(msg="Lane-level 30-minute bucket would exceed capacity"):
    return ApiError("ERR_LANE_CAPACITY_EXCEEDED", 409, msg)


def err_slot_family(msg="Slot family not in an eligible status or belongs to a different campaign"):
    return ApiError("ERR_SLOT_FAMILY_MISMATCH", 422, msg)


def err_stage_mismatch(msg="Gift staged into a slot for a different family, or event not in SORTING"):
    return ApiError("ERR_STAGE_SLOT_MISMATCH", 422, msg)


def err_outside_window(msg="Check-in attempted before window_start or after window_end"):
    return ApiError("ERR_OUTSIDE_SLOT_WINDOW", 409, msg)


def err_backfill_budget(msg="mark-purchased would exceed campaign.backfill_budget_cents"):
    return ApiError("ERR_BACKFILL_BUDGET_EXCEEDED", 422, msg)


def err_campaign_not_closed(msg="Campaign is not in RECONCILIATION or CLOSED"):
    return ApiError("ERR_CAMPAIGN_NOT_CLOSED", 409, msg)


def err_donor_opted_out(msg="Donor has opted out of thank-you outreach"):
    return ApiError("ERR_DONOR_OPTED_OUT", 409, msg)
