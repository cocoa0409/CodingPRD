"""Error catalog and exception type.

Every error_id and its HTTP status is taken verbatim from PRD.md section 5
(Error Catalog) / SCAFFOLD.yaml `errors`.
"""

# ---------------------------------------------------------------------------
# error_id -> (http_status, default message)
# ---------------------------------------------------------------------------
ERROR_CATALOG = {
    # --- authentication / authorization -----------------------------------
    "ERR_UNAUTHENTICATED": (401, "Missing or unrecognised authentication headers"),
    "ERR_UNAUTHORIZED": (403, "Role is not permitted to perform this operation"),
    "ERR_FORBIDDEN_RESOURCE_OWNERSHIP": (403, "Caller does not own the addressed resource"),
    "ERR_SEGREGATION_OF_DUTIES": (403, "Segregation of duties prohibits this action"),

    # --- existence --------------------------------------------------------
    "ERR_PLAN_NOT_FOUND": (404, "Bonus plan not found"),
    "ERR_METRIC_NOT_FOUND": (404, "Company metric not found"),
    "ERR_BUSINESS_UNIT_NOT_FOUND": (404, "Business unit not found"),
    "ERR_JOB_LEVEL_TARGET_NOT_FOUND": (404, "Job level target not found"),
    "ERR_PARTICIPANT_NOT_FOUND": (404, "Participant not found"),
    "ERR_EVENT_NOT_FOUND": (404, "Eligibility event not found"),
    "ERR_POOL_NOT_FOUND": (404, "Business unit pool not found"),
    "ERR_AWARD_NOT_FOUND": (404, "Participant award not found"),
    "ERR_ADJUSTMENT_NOT_FOUND": (404, "Discretionary adjustment not found"),
    "ERR_ACCRUAL_PERIOD_NOT_FOUND": (404, "Accrual period not found"),
    "ERR_PAYOUT_RUN_NOT_FOUND": (404, "Payout run not found"),
    "ERR_DISPUTE_NOT_FOUND": (404, "Dispute not found"),

    # --- request shape ----------------------------------------------------
    "ERR_INVALID_REQUEST": (400, "Request payload is malformed or incomplete"),

    # --- field relationships / uniqueness ---------------------------------
    "ERR_DUPLICATE_RESOURCE": (409, "A resource with the same natural key already exists"),
    "ERR_PLAN_WEIGHTS_INVALID": (422, "Funding weights must sum to exactly 100.00"),
    "ERR_PLAN_PERIOD_INVALID": (422, "Plan period or payment date is invalid"),
    "ERR_METRIC_BAND_INVALID": (422, "Metric threshold/target/max band is invalid"),
    "ERR_GUIDELINE_BAND_INVALID": (422, "Guideline ratio band is invalid"),

    # --- lifecycle --------------------------------------------------------
    "ERR_PLAN_STATE_INVALID": (409, "Bonus plan is not in a state that allows this operation"),
    "ERR_PLAN_NOT_IN_SETUP": (409, "Bonus plan is no longer in setup"),
    "ERR_PLAN_NOT_IN_ALLOCATION": (409, "Bonus plan is not open for allocation"),
    "ERR_PLAN_NOT_LOCKED": (409, "Bonus plan is not in the required locked stage"),
    "ERR_PLAN_ALREADY_SETTLED": (409, "Bonus plan has already been paid out or settled"),
    "ERR_METRIC_ACTUAL_ALREADY_FILED": (409, "Metric actual has already been filed"),
    "ERR_POOL_STATE_INVALID": (409, "Business unit pool is not in a state that allows this operation"),
    "ERR_POOL_NOT_ALLOCATING": (409, "Business unit pool is not accepting allocations"),
    "ERR_AWARD_STATE_INVALID": (409, "Participant award is not in a state that allows this operation"),
    "ERR_ADJUSTMENT_NOT_PENDING": (409, "Discretionary adjustment is not in the required state"),
    "ERR_ACCRUAL_ALREADY_POSTED": (409, "Accrual period is not in the required state"),
    "ERR_PAYOUT_ALREADY_EXECUTED": (409, "Payout run is not in the required state"),
    "ERR_DISPUTE_NOT_UNDER_REVIEW": (409, "Dispute is not in the required state"),
    "ERR_DISPUTE_NOT_ALLOWED_YET": (409, "Disputes may not be filed for this plan yet"),

    # --- optimistic concurrency -------------------------------------------
    "ERR_STALE_POOL_VERSION": (412, "Pool version precondition failed"),
    "ERR_STALE_PLAN_VERSION": (412, "Plan version precondition failed"),

    # --- governance safety ------------------------------------------------
    "ERR_ADJUSTMENT_DOCUMENTATION_REQUIRED": (422, "Documentation reference is required for this adjustment size"),
    "ERR_GOVERNANCE_POSTURE_BREACHED": (409, "Plan governance posture is BREACHED"),

    # --- temporal ---------------------------------------------------------
    "ERR_EVENT_DATE_OUTSIDE_PLAN_PERIOD": (422, "Event effective date falls outside the plan period"),
    "ERR_EVENT_DATE_BEFORE_HIRE": (422, "Event effective date precedes the participant hire date"),
    "ERR_LEAVE_INTERVAL_OVERLAP": (409, "Leave interval overlaps an existing leave interval"),
    "ERR_PARTICIPANT_ALREADY_TERMINATED": (409, "Participant is already terminated"),
    "ERR_ACCRUAL_PERIOD_OVERLAP": (409, "Accrual period overlaps an existing period"),
    "ERR_ACCRUAL_PERIOD_GAP": (422, "Accrual periods must be contiguous"),
    "ERR_ACCRUAL_REVERSAL_OUT_OF_ORDER": (409, "Accrual reversals must proceed newest first"),
    "ERR_PAYMENT_DATE_NOT_REACHED": (409, "Plan payment date has not been reached"),

    # --- referential ------------------------------------------------------
    "ERR_PLAN_SCOPE_MISMATCH": (422, "Referenced resources do not belong to the same plan"),
    "ERR_JOB_LEVEL_TARGET_MISSING": (422, "No job level target exists for a participant segment"),
    "ERR_POOL_MISSING_FOR_UNIT": (422, "No business unit pool exists for the resolved business unit"),
    "ERR_SUPERSEDES_EVENT_INVALID": (422, "Superseded event reference is invalid"),
    "ERR_METRIC_WEIGHTS_INVALID": (422, "Company metric weights must sum to exactly 100.00"),
    "ERR_METRICS_NOT_ALL_ACTUALIZED": (409, "Every company metric must have an actual filed"),
    "ERR_SCORECARDS_NOT_ALL_CERTIFIED": (409, "Every business unit scorecard must be certified"),
    "ERR_NO_ELIGIBLE_PARTICIPANTS": (409, "Plan has no eligible target to fund"),
    "ERR_POOL_CALIBRATION_PENDING": (409, "One or more pools have not completed calibration"),
    "ERR_DEFERRED_AWARDS_PENDING": (409, "Deferred awards remain unresolved"),

    # --- distribution -----------------------------------------------------
    "ERR_FUNDING_MULTIPLIER_ZERO": (409, "Funding multiplier is zero; no pool can be funded"),
    "ERR_AWARD_NOT_ELIGIBLE": (422, "Award is not eligible for allocation"),
    "ERR_GUIDELINE_RATIO_BREACH": (422, "Proposed allocation falls outside the guideline band"),
    "ERR_TOP_TIER_CONCENTRATION": (422, "Top tier award concentration cap exceeded"),
    "ERR_POOL_NOT_WITHIN_GUIDELINES": (422, "Pool is not within its distribution guidelines"),
    "ERR_AWARD_HAS_APPROVED_ADJUSTMENT": (409, "Award carries an approved discretionary adjustment"),
    "ERR_NEGATIVE_AWARD_NOT_ALLOWED": (422, "Resulting award would be negative"),
    "ERR_DISPUTE_ADJUSTMENT_EXCEEDS_LIMIT": (422, "Dispute adjustment exceeds the permitted limit"),

    # --- fiscal -----------------------------------------------------------
    "ERR_ADJUSTMENT_EXCEEDS_PER_AWARD_LIMIT": (422, "Adjustment exceeds the per award cap"),
    "ERR_POOL_FUNDS_EXCEEDED": (422, "Allocation would exceed the pool funded amount"),
    "ERR_DISCRETIONARY_BUDGET_EXCEEDED": (422, "Adjustment would exceed the plan discretionary budget"),
}


class ApiError(Exception):
    """Domain error carrying the scaffold error_id and its HTTP status."""

    def __init__(self, error_id, message=None, http_status=None):
        status, default_message = ERROR_CATALOG.get(
            error_id, (400, "Request could not be processed")
        )
        self.error_id = error_id
        self.message = message or default_message
        self.http_status = http_status or status
        super().__init__(self.message)


def api_error(error_id, message=None):
    return ApiError(error_id, message)


def raise_error(error_id, message=None):
    raise ApiError(error_id, message)
