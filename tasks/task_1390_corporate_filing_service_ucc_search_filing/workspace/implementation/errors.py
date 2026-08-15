"""API error type carrying the scaffold-defined error_id, HTTP status and message."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- Error factory helpers (id, status) per the error catalogue (PRD section 5) ---

def err_missing_context():
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                    "X-User-ID and X-User-Role headers are required and the role must be recognized")


def err_invalid_request(msg="Request body failed structural validation"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_target_filing_required():
    return ApiError("ERR_TARGET_FILING_REQUIRED", 400,
                    "target_filing_id is required when kind is not NEW_UCC1")


def err_unauthorized_role():
    return ApiError("ERR_UNAUTHORIZED_ROLE", 403, "Role is not permitted for this endpoint")


def err_ownership():
    return ApiError("ERR_CLIENT_OWNERSHIP_MISMATCH", 403,
                    "ClientManager may only act on its own client account")


def err_segregation():
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                    "approve-preparation must be performed by a different user than submit-intake")


def err_not_found(kind):
    mapping = {
        "client": "ERR_CLIENT_NOT_FOUND",
        "jurisdiction": "ERR_JURISDICTION_NOT_FOUND",
        "debtor": "ERR_DEBTOR_NOT_FOUND",
        "secured_party": "ERR_SECURED_PARTY_NOT_FOUND",
        "request": "ERR_REQUEST_NOT_FOUND",
        "filing": "ERR_FILING_NOT_FOUND",
        "search": "ERR_SEARCH_NOT_FOUND",
        "report": "ERR_REPORT_NOT_FOUND",
    }
    return ApiError(mapping[kind], 404, f"{kind} not found")


def err_duplicate_state_code():
    return ApiError("ERR_DUPLICATE_STATE_CODE", 409,
                    "A jurisdiction profile with this state_code already exists")


def err_client_suspended():
    return ApiError("ERR_CLIENT_SUSPENDED", 409,
                    "Client account is suspended; submit-intake is blocked")


def err_request_invalid_state(msg="FilingRequest is not in a valid state for this transition"):
    return ApiError("ERR_REQUEST_INVALID_STATE", 409, msg)


def err_request_in_process():
    return ApiError("ERR_REQUEST_IN_PROCESS", 409,
                    "Request is IN_PROCESS and cannot be cancelled")


def err_request_not_ready():
    return ApiError("ERR_REQUEST_NOT_READY", 409,
                    "Parent filing request must be READY")


def err_attempt_in_flight():
    return ApiError("ERR_ATTEMPT_IN_FLIGHT", 409,
                    "Request already has a non-terminal (DRAFT or SUBMITTED) attempt")


def err_ucc3_in_flight():
    return ApiError("ERR_UCC3_IN_FLIGHT", 409,
                    "Root filing already has an open AMENDMENT or CONTINUATION request")


def err_filing_invalid_state(msg="Filing is not in a valid state for this transition"):
    return ApiError("ERR_FILING_INVALID_STATE", 409, msg)


def err_target_not_active():
    return ApiError("ERR_TARGET_FILING_NOT_ACTIVE", 409,
                    "Target/subject filing must be ACTIVE")


def err_search_not_ordered():
    return ApiError("ERR_SEARCH_NOT_ORDERED", 409,
                    "record-results requires the search to be ORDERED")


def err_overlapping():
    return ApiError("ERR_OVERLAPPING_ACTIVE_FILING", 409,
                    "Another ACTIVE INITIAL filing exists for the same debtor, jurisdiction and office")


def err_expedited_capacity():
    return ApiError("ERR_EXPEDITED_CAPACITY_REACHED", 409,
                    "Expedited daily capacity reached for this jurisdiction")


def err_stale_version():
    return ApiError("ERR_STALE_VERSION", 412,
                    "Expected version does not match the resource's current version")


def err_county_required():
    return ApiError("ERR_COUNTY_REQUIRED", 400,
                    "filing_office resolved to COUNTY but county_name is absent")


def err_county_not_in_jurisdiction():
    return ApiError("ERR_COUNTY_NOT_IN_JURISDICTION", 422,
                    "county_name is not a member of the jurisdiction's county_names")


def err_name_misleading():
    return ApiError("ERR_DEBTOR_NAME_SERIOUSLY_MISLEADING", 422,
                    "Normalized debtor name on filing does not equal the name of record")


def err_dl_name_missing():
    return ApiError("ERR_DEBTOR_DL_NAME_MISSING", 422,
                    "Individual debtor in a DL_SAFE_HARBOR jurisdiction has no drivers_license_name")


def err_collateral_insufficient():
    return ApiError("ERR_COLLATERAL_INSUFFICIENTLY_DESCRIBED", 422,
                    "collateral_text is missing, shorter than 20 characters, or supergeneric")


def err_collateral_not_present():
    return ApiError("ERR_COLLATERAL_NOT_PRESENT", 422,
                    "collateral_text is not a substring of the root filing's collateral_text")


def err_continuation_outside_window():
    return ApiError("ERR_CONTINUATION_OUTSIDE_WINDOW", 422,
                    "filed_at is outside the continuation window [expiration-6mo, expiration)")


def err_refile_window_expired():
    return ApiError("ERR_REFILE_WINDOW_EXPIRED", 422,
                    "Refile attempted more than 30 days after the latest rejection")


def err_search_stale():
    return ApiError("ERR_SEARCH_STALE", 422,
                    "Supporting search is not COMPLETED or its through_date is more than 90 days old")


def err_through_date_too_early():
    return ApiError("ERR_SEARCH_THROUGH_DATE_TOO_EARLY", 422,
                    "through_date is earlier than the subject filing's filed_at")


def err_invalid_filed_at():
    return ApiError("ERR_INVALID_FILED_AT", 422,
                    "filed_at must be within [submitted_at, now] (both bounds inclusive)")


def err_fee_exceeded():
    return ApiError("ERR_FEE_AUTHORIZATION_EXCEEDED", 402,
                    "Charged fee exceeds the request's fee_authorization_cents")
