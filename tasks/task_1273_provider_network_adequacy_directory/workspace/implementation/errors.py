"""Error classes carrying error_id, message and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- auth ---
def err_missing_context(msg="X-User-ID or X-User-Role header missing or role unrecognized"):
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", msg, 400)


def err_forbidden(msg="Caller role not permitted on this endpoint"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def err_not_owner(msg="Entity-backed identity mismatch"):
    return ApiError("ERR_NOT_RESOURCE_OWNER", msg, 403)


def err_segregation(msg="Correction verifier X-User-ID equals correction.submitted_by_user_id"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES_VIOLATION", msg, 403)


# --- request shape ---
def err_invalid(msg="Malformed payload, missing required field, or invalid value"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


# --- not found ---
def err_region_not_found(msg="region id does not exist"):
    return ApiError("ERR_REGION_NOT_FOUND", msg, 404)


def err_standard_not_found(msg="standard id does not exist"):
    return ApiError("ERR_STANDARD_NOT_FOUND", msg, 404)


def err_provider_not_found(msg="provider id does not exist"):
    return ApiError("ERR_PROVIDER_NOT_FOUND", msg, 404)


def err_location_not_found(msg="location id does not exist"):
    return ApiError("ERR_LOCATION_NOT_FOUND", msg, 404)


def err_listing_not_found(msg="listing id does not exist"):
    return ApiError("ERR_LISTING_NOT_FOUND", msg, 404)


def err_member_not_found(msg="member id does not exist"):
    return ApiError("ERR_MEMBER_NOT_FOUND", msg, 404)


def err_cycle_not_found(msg="attestation cycle id does not exist"):
    return ApiError("ERR_CYCLE_NOT_FOUND", msg, 404)


def err_record_not_found(msg="attestation record id does not exist"):
    return ApiError("ERR_ATTESTATION_RECORD_NOT_FOUND", msg, 404)


def err_probe_not_found(msg="probe id does not exist"):
    return ApiError("ERR_PROBE_NOT_FOUND", msg, 404)


def err_evaluation_not_found(msg="evaluation id does not exist"):
    return ApiError("ERR_EVALUATION_NOT_FOUND", msg, 404)


def err_deficiency_not_found(msg="deficiency id does not exist"):
    return ApiError("ERR_DEFICIENCY_NOT_FOUND", msg, 404)


def err_apr_not_found(msg="access plan request id does not exist"):
    return ApiError("ERR_ACCESS_PLAN_REQUEST_NOT_FOUND", msg, 404)


def err_complaint_not_found(msg="complaint id does not exist"):
    return ApiError("ERR_COMPLAINT_NOT_FOUND", msg, 404)


def err_correction_not_found(msg="correction id does not exist"):
    return ApiError("ERR_CORRECTION_NOT_FOUND", msg, 404)


# --- state ---
def err_provider_invalid_transition(msg="PATCH providers to_status not allowed from current provider status"):
    return ApiError("ERR_PROVIDER_INVALID_TRANSITION", msg, 409)


def err_provider_not_effective(msg="Operation requires provider.status == EFFECTIVE"):
    return ApiError("ERR_PROVIDER_NOT_EFFECTIVE", msg, 409)


def err_listing_invalid_transition(msg="Listing to_status/reason combination not allowed from current status"):
    return ApiError("ERR_LISTING_INVALID_TRANSITION", msg, 409)


def err_listing_not_listed(msg="Probe create requires listing.status == LISTED"):
    return ApiError("ERR_LISTING_NOT_LISTED", msg, 409)


def err_listing_removed(msg="Target listing is REMOVED"):
    return ApiError("ERR_LISTING_REMOVED", msg, 409)


def err_listing_attestation_unresolved(msg="Reinstate from ATTESTATION_FAILURE requires a resolved attestation record"):
    return ApiError("ERR_LISTING_ATTESTATION_UNRESOLVED", msg, 409)


def err_listing_ghost_unresolved(msg="Reinstate from GHOST_CONFIRMED requires a later PASS probe"):
    return ApiError("ERR_LISTING_GHOST_UNRESOLVED", msg, 409)


def err_cycle_invalid_state(msg="Cycle advance not allowed from current cycle status"):
    return ApiError("ERR_CYCLE_INVALID_STATE", msg, 409)


def err_record_not_respondable(msg="Record not in a respondable combination of (record.status, cycle.status)"):
    return ApiError("ERR_RECORD_NOT_RESPONDABLE", msg, 409)


def err_probe_invalid_state(msg="Probe already RECORDED or otherwise not SCHEDULED"):
    return ApiError("ERR_PROBE_INVALID_STATE", msg, 409)


def err_evaluation_invalid_state(msg="Evaluation not OPEN for finalize"):
    return ApiError("ERR_EVALUATION_INVALID_STATE", msg, 409)


def err_unrecorded_probes(msg="Finalize blocked: SCHEDULED probes with requested_date inside the measurement period exist"):
    return ApiError("ERR_UNRECORDED_PROBES_EXIST", msg, 409)


def err_deficiency_not_open(msg="Deficiency must be OPEN to create a request or to approve one"):
    return ApiError("ERR_DEFICIENCY_NOT_OPEN", msg, 409)


def err_request_not_submittable(msg="Access plan request not in DRAFT or DENIED"):
    return ApiError("ERR_REQUEST_NOT_SUBMITTABLE", msg, 409)


def err_request_not_decidable(msg="Access plan request not SUBMITTED"):
    return ApiError("ERR_REQUEST_NOT_DECIDABLE", msg, 409)


def err_complaint_not_open(msg="Complaint not OPEN for adjudication"):
    return ApiError("ERR_COMPLAINT_NOT_OPEN", msg, 409)


def err_correction_not_verifiable(msg="Correction not SUBMITTED"):
    return ApiError("ERR_CORRECTION_NOT_VERIFIABLE", msg, 409)


def err_member_not_enrolled(msg="Member must be ENROLLED"):
    return ApiError("ERR_MEMBER_NOT_ENROLLED", msg, 409)


# --- temporal ---
def err_cycle_not_advanceable(msg="Clock date has not reached the gate date for the next cycle transition"):
    return ApiError("ERR_CYCLE_NOT_YET_ADVANCEABLE", msg, 422)


def err_complaint_window(msg="filed_date - error_observed_date > 90 days, or error_observed_date in the future"):
    return ApiError("ERR_COMPLAINT_WINDOW_EXPIRED", msg, 422)


def err_probe_date_order(msg="offered_appointment_date < requested_date, or requested_date after current clock date"):
    return ApiError("ERR_PROBE_DATE_ORDER", msg, 422)


def err_excuse_window_invalid(msg="excuse_through_date < excuse_start_date, or excuse_start_date before current clock date"):
    return ApiError("ERR_EXCUSE_WINDOW_INVALID", msg, 422)


# --- referential ---
def err_location_provider_mismatch(msg="listing.location_id belongs to a different provider than listing.provider_id"):
    return ApiError("ERR_LOCATION_PROVIDER_MISMATCH", msg, 422)


def err_listing_not_in_member_region(msg="Complaint listing's location region differs from the filing member's region"):
    return ApiError("ERR_LISTING_NOT_IN_MEMBER_REGION", msg, 422)


def err_correction_listing_mismatch(msg="correction.complaint_id references a complaint whose listing_id differs"):
    return ApiError("ERR_CORRECTION_LISTING_MISMATCH", msg, 422)


def err_specialty_standard_missing(msg="No NetworkStandard for (listing.specialty, location region's geo_class)"):
    return ApiError("ERR_SPECIALTY_STANDARD_MISSING", msg, 422)


# --- constraint ---
def err_npi_duplicate(msg="npi already registered"):
    return ApiError("ERR_NPI_DUPLICATE", msg, 409)


def err_region_duplicate(msg="county_fips already registered"):
    return ApiError("ERR_REGION_DUPLICATE", msg, 409)


def err_member_ref_duplicate(msg="member_ref already registered"):
    return ApiError("ERR_MEMBER_REF_DUPLICATE", msg, 409)


def err_standard_duplicate(msg="(specialty, geo_class) standard already exists"):
    return ApiError("ERR_STANDARD_DUPLICATE", msg, 409)


def err_listing_already_listed(msg="A LISTED listing already exists for (location_id, specialty)"):
    return ApiError("ERR_LISTING_ALREADY_LISTED", msg, 409)


def err_cycle_window_overlap(msg="New cycle window overlaps an existing cycle window"):
    return ApiError("ERR_CYCLE_WINDOW_OVERLAP", msg, 409)


def err_cycle_already_active(msg="Another cycle is OPEN or OUTREACH when advancing to OPEN"):
    return ApiError("ERR_CYCLE_ALREADY_ACTIVE", msg, 409)


def err_excuse_window_overlap(msg="Approving would overlap another APPROVED request's excuse window for the same deficiency"):
    return ApiError("ERR_EXCUSE_WINDOW_OVERLAP", msg, 409)


def err_evaluation_already_open(msg="Another AdequacyEvaluation is OPEN"):
    return ApiError("ERR_EVALUATION_ALREADY_OPEN", msg, 409)


# --- OCC ---
def err_stale_standard(msg="expected_standard_version does not match current NetworkStandard.version"):
    return ApiError("ERR_STALE_STANDARD_VERSION", msg, 412)


def err_stale_location(msg="expected_location_version does not match current PracticeLocation.version"):
    return ApiError("ERR_STALE_LOCATION_VERSION", msg, 412)


def err_stale_listing(msg="expected_listing_version does not match current DirectoryListing.version"):
    return ApiError("ERR_STALE_LISTING_VERSION", msg, 412)


def err_stale_deficiency(msg="expected_deficiency_version does not match current DeficiencyRecord.version"):
    return ApiError("ERR_STALE_DEFICIENCY_VERSION", msg, 412)
