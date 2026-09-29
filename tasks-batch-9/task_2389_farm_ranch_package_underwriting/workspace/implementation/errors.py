"""Error catalog (§1.6 / PRD §5) and the ApiError exception."""

ERROR_CATALOG = {
    # ---- authentication / authorization
    "ERR_UNAUTHENTICATED": (401, "Missing or blank X-User-ID header."),
    "ERR_FORBIDDEN_ROLE": (403, "Your role may not perform this operation."),
    "ERR_NOT_ACCOUNT_AGENT": (403, "This account belongs to another producer."),
    "ERR_NOT_ASSIGNED_INSPECTOR": (403, "Only the assigned inspector may complete this inspection."),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The underwriter who referred this policy may not decide the referral."),
    # ---- schema
    "ERR_INVALID_REQUEST": (400, "Request body or query parameters are invalid."),
    "ERR_INVALID_TERM_DATES": (400, "term_end_date must be after term_start_date and the term must span at least 90 days."),
    # ---- existence
    "ERR_AGENT_NOT_FOUND": (404, "Agent not found."),
    "ERR_INSPECTOR_NOT_FOUND": (404, "Inspector not found."),
    "ERR_CAT_POOL_NOT_FOUND": (404, "Catastrophe capacity pool not found."),
    "ERR_FARM_ACCOUNT_NOT_FOUND": (404, "Farm account not found."),
    "ERR_FARM_POLICY_NOT_FOUND": (404, "Farm policy not found."),
    "ERR_SCHEDULED_ITEM_NOT_FOUND": (404, "Scheduled item not found."),
    "ERR_LABOR_PROFILE_NOT_FOUND": (404, "Labor profile not found."),
    "ERR_ENDORSEMENT_NOT_FOUND": (404, "Endorsement not found."),
    "ERR_CAT_RESERVATION_NOT_FOUND": (404, "Catastrophe reservation not found."),
    "ERR_INSPECTION_NOT_FOUND": (404, "Inspection not found."),
    "ERR_RECOMMENDATION_NOT_FOUND": (404, "Recommendation not found."),
    # ---- optimistic concurrency
    "ERR_STALE_POLICY_VERSION": (412, "The policy has changed since you last read it; re-read and retry."),
    "ERR_STALE_POOL_VERSION": (412, "The capacity pool has changed since you last read it; re-read and retry."),
    # ---- state
    "ERR_POLICY_NOT_IN_DRAFT": (409, "The policy must be in DRAFT for this operation."),
    "ERR_POLICY_NOT_RATED": (409, "The policy must be RATED for this operation."),
    "ERR_POLICY_NOT_REFERRED": (409, "The policy is not awaiting a referral decision."),
    "ERR_POLICY_NOT_BOUND": (409, "The policy must be BOUND for this operation."),
    "ERR_POLICY_TERMINAL": (409, "The policy is closed and can no longer be modified."),
    "ERR_ENDORSEMENT_NOT_REQUESTED": (409, "Only a REQUESTED endorsement can be decided."),
    "ERR_ENDORSEMENT_NOT_APPROVED": (409, "Only an approved or suspended endorsement can be rescinded."),
    "ERR_INSPECTION_STATE_INVALID": (409, "The inspection is not in a state that allows this operation."),
    "ERR_RECOMMENDATION_STATE_INVALID": (409, "The recommendation is not in a state that allows this operation."),
    "ERR_WC_STATE_INVALID": (409, "The labor profile is not awaiting workers-compensation verification."),
    # ---- conditional fields
    "ERR_BLANKET_LIMIT_REQUIRED": (422, "blanket_limit_cents is required for a BLANKET limit basis and forbidden for PER_HEAD."),
    "ERR_PEAK_SEASON_FIELDS_REQUIRED": (422, "Seasonal value fields are required for stored crops, hay and inputs and forbidden for other item classes."),
    "ERR_VISITOR_COUNT_REQUIRED": (422, "annual_visitor_count is required for an agritourism exposure and forbidden for other exposure types."),
    # ---- business safety
    "ERR_COMPLIANCE_SUSPENDED": (409, "The policy is suspended for outstanding loss-control findings."),
    "ERR_CRITICAL_REC_OVERDUE": (422, "A critical loss-control recommendation is overdue."),
    "ERR_BUYBACK_INSPECTION_REQUIRED": (422, "This endorsement requires a completed loss-control inspection."),
    "ERR_BUYBACK_HAZARD_TOO_HIGH": (422, "The latest inspection hazard score is too high for this buy-back."),
    # ---- business constraints
    "ERR_DUPLICATE_POOL": (409, "A capacity pool already exists for this zone and peril."),
    "ERR_INSPECTOR_WINDOW_CONFLICT": (409, "The inspector already holds an inspection overlapping this window."),
    "ERR_INSPECTOR_DAY_CAPACITY_EXCEEDED": (409, "The inspector's daily capacity would be exceeded."),
    "ERR_OVERLAPPING_POLICY_TERM": (409, "Another live policy on this account already covers part of this term."),
    "ERR_INSPECTOR_INACTIVE": (422, "The inspector is not active."),
    "ERR_ENDORSEMENT_EXPOSURE_MISSING": (422, "The policy lacks the liability exposure this endorsement modifies."),
    # ---- business referential
    "ERR_AGENT_NOT_ACTIVE": (422, "The producer's appointment is suspended."),
    "ERR_WC_COORDINATION_UNVERIFIED": (422, "Workers-compensation coordination is not verified."),
    "ERR_WC_PROOF_MISSING": (422, "Workers-compensation proof details are missing."),
    # ---- business temporal
    "ERR_QUOTE_EXPIRED": (409, "The quote has expired; re-rate the policy."),
    "ERR_WC_PROOF_EXPIRED": (422, "The workers-compensation proof on file has expired."),
    # ---- business fiscal
    "ERR_CAT_POOL_NOT_CONFIGURED": (422, "No catastrophe capacity pool is configured for this zone and peril."),
    "ERR_NO_RATEABLE_EXPOSURE": (422, "The policy has no rateable property or livestock exposure."),
    "ERR_POOL_FROZEN": (409, "The catastrophe capacity pool is frozen."),
    "ERR_CAT_CAPACITY_EXCEEDED": (409, "The catastrophe capacity pool cannot absorb this exposure."),
    "ERR_AGENT_AUTHORITY_EXCEEDED": (422, "The premium exceeds the producer's binding authority."),
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        status, default_message = ERROR_CATALOG.get(error_id, (400, error_id))
        self.error_id = error_id
        self.http_status = http_status or status
        self.message = message or default_message
        super().__init__(self.message)


def bad_request(message=None):
    return ApiError("ERR_INVALID_REQUEST", message)
