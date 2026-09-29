"""Error catalog (PRD section 5 / scaffold section 1.6)."""

ERROR_CATALOG = {
    # authentication / authorization
    "ERR_MISSING_ROLE": (401, "X-User-Role header is required"),
    "ERR_INVALID_ROLE": (401, "X-User-Role is not a recognized role"),
    "ERR_UNAUTHORIZED": (403, "This role may not perform this operation"),
    "ERR_INVALID_USER_CONTEXT": (
        401,
        "X-User-ID is required and must name an existing analyst for this role",
    ),
    "ERR_NOT_CASE_OWNER": (
        403,
        "Only the assigned analyst or a review lead may resolve this case",
    ),
    # request shape
    "ERR_VALIDATION": (422, "Request body failed field-level validation"),
    # existence
    "ERR_CUSTOMER_NOT_FOUND": (404, "Customer not found"),
    "ERR_ANALYST_NOT_FOUND": (404, "Analyst not found"),
    "ERR_DEVICE_NOT_FOUND": (404, "Device profile not found"),
    "ERR_ADDRESS_NOT_FOUND": (404, "Address record not found"),
    "ERR_RULE_PACK_NOT_FOUND": (404, "Rule pack not found"),
    "ERR_RULE_NOT_FOUND": (404, "Fraud rule not found"),
    "ERR_RISK_MODEL_NOT_FOUND": (404, "Risk model not found"),
    "ERR_ASSESSMENT_NOT_FOUND": (404, "Checkout assessment not found"),
    "ERR_CASE_NOT_FOUND": (404, "Review case not found"),
    "ERR_AUTH_EVENT_NOT_FOUND": (404, "Auth event not found"),
    "ERR_CHARGEBACK_NOT_FOUND": (404, "Chargeback record not found"),
    "ERR_EXCEPTION_NOT_FOUND": (404, "Policy exception not found"),
    # state
    "ERR_ASSESSMENT_ALREADY_SCORED": (409, "Assessment has already been scored"),
    "ERR_CUSTOMER_ACCOUNT_LOCKED": (409, "Customer account is not ACTIVE"),
    "ERR_CUSTOMER_ATO_CONTAINED": (
        409,
        "Customer is under account-takeover containment",
    ),
    "ERR_CUSTOMER_POSTURE_INVALID": (
        409,
        "Requested posture transition is not permitted from the current state",
    ),
    "ERR_CASE_STATE_INVALID": (
        409,
        "Review case state does not permit this operation",
    ),
    "ERR_CHARGEBACK_TRANSITION_INVALID": (
        409,
        "Chargeback transition is not permitted from the current state",
    ),
    "ERR_MODEL_TRANSITION_INVALID": (
        409,
        "Risk model transition is not permitted from the current status",
    ),
    "ERR_RULE_PACK_NOT_DRAFT": (409, "Rule pack must be in DRAFT for this operation"),
    "ERR_EXCEPTION_STATE_INVALID": (
        409,
        "Policy exception state does not permit this decision",
    ),
    "ERR_CHALLENGE_STATE_INVALID": (
        409,
        "Challenge state does not permit this action",
    ),
    "ERR_CHALLENGE_EXPIRED": (409, "Step-up challenge has expired"),
    "ERR_CHALLENGE_NOT_EXPIRED": (409, "Step-up challenge has not expired yet"),
    # optimistic concurrency
    "ERR_STALE_ANALYST_VERSION": (412, "Analyst has been modified since it was read"),
    "ERR_STALE_CUSTOMER_VERSION": (412, "Customer has been modified since it was read"),
    # segregation of duties
    "ERR_ACTIVATION_SEGREGATION_VIOLATION": (
        409,
        "A rule pack may not be activated by the user that created it",
    ),
    "ERR_DECISION_SEGREGATION_VIOLATION": (
        409,
        "A policy exception may not be approved or rejected by its requester",
    ),
    "ERR_ESCALATION_SEGREGATION_VIOLATION": (
        409,
        "An escalated case may not be reassigned to the analyst that escalated it",
    ),
    # referential / cross-entity
    "ERR_ESCALATED_REQUIRES_LEAD": (
        422,
        "An escalated case may only be assigned to a LEAD analyst",
    ),
    "ERR_ANALYST_SKILL_MISMATCH": (
        422,
        "Analyst does not cover this case's primary signal family",
    ),
    "ERR_ANALYST_NOT_AVAILABLE": (409, "Analyst is not AVAILABLE"),
    "ERR_RULE_PACK_NOT_ACTIVE": (
        409,
        "The rule pack pinned to this assessment is no longer ACTIVE",
    ),
    "ERR_RISK_MODEL_NOT_ACTIVE": (
        409,
        "The risk model pinned to this assessment is no longer ACTIVE",
    ),
    "ERR_NO_ACTIVE_RULE_PACK": (422, "No ACTIVE rule pack covers the current instant"),
    "ERR_NO_ACTIVE_RISK_MODEL": (422, "No ACTIVE risk model is available"),
    "ERR_EXCEPTION_SCOPE_ADDRESS_REQUIRED": (
        422,
        "whitelisted_address_id is required for an ADDRESS_WHITELIST exception",
    ),
    "ERR_EXCEPTION_ADDRESS_NOT_ALLOWED": (
        422,
        "whitelisted_address_id is only valid for an ADDRESS_WHITELIST exception",
    ),
    "ERR_ADDRESS_CLUSTER_DEPTH": (
        422,
        "Address clusters are single-level: the canonical parent must itself be a root",
    ),
    "ERR_CHARGEBACK_ASSESSMENT_NOT_APPROVED": (
        422,
        "A chargeback may only be filed against an approved assessment",
    ),
    "ERR_RULE_FAMILY_MISMATCH": (
        422,
        "signal_family does not match the rule code's family",
    ),
    # temporal
    "ERR_INVALID_WINDOW": (422, "Window end must be strictly after window start"),
    "ERR_CHARGEBACK_BEFORE_DECISION": (
        422,
        "received_at may not precede the assessment's decision instant",
    ),
    "ERR_TRAINING_CUTOFF_IN_FUTURE": (
        422,
        "trained_on_chargeback_cutoff_at may not be in the future",
    ),
    "ERR_CLOCK_NOT_MONOTONIC": (422, "The logical clock may not move backwards"),
    # constraint
    "ERR_RULE_PACK_WINDOW_OVERLAP": (
        409,
        "Rule pack windows must be separated by more than the activation freeze buffer",
    ),
    "ERR_ANALYST_CAPACITY_EXCEEDED": (409, "Analyst is already at shift capacity"),
    "ERR_NO_ELIGIBLE_ANALYST": (422, "No analyst satisfies the auto-assignment selector"),
    "ERR_RULE_PACK_EMPTY": (
        422,
        "A rule pack must contain at least one rule before activation",
    ),
    "ERR_EXCEPTION_WINDOW_OVERLAP": (
        409,
        "An open exception of the same scope already covers part of this window",
    ),
    "ERR_DUPLICATE_DEVICE_HASH": (409, "device_hash is already registered"),
    "ERR_DUPLICATE_RULE_CODE": (409, "This rule code already exists in the pack"),
    "ERR_CHALLENGE_ATTEMPTS_EXHAUSTED": (
        409,
        "The step-up challenge attempt budget is exhausted",
    ),
    "ERR_TRAINING_SEGMENT_UNDERFILLED": (
        422,
        "A required reason-code training segment has too few LOST chargebacks",
    ),
    # fiscal
    "ERR_WEIGHTS_NOT_NORMALIZED": (422, "rule_weight and model_weight must sum to 1.00"),
    "ERR_INVALID_SCORE_BANDS": (
        422,
        "review_floor_score must be strictly below decline_floor_score",
    ),
    "ERR_EXCEPTION_AMOUNT_EXCEEDS_TIER_CAP": (
        422,
        "max_amount_cents exceeds the customer tier's exception cap",
    ),
    "ERR_EXCEPTION_TIER_NOT_ELIGIBLE": (
        422,
        "This customer tier is not eligible for an auto-approval exception",
    ),
    "ERR_CHARGEBACK_AMOUNT_EXCEEDS_ORDER": (
        422,
        "Disputed amount may not exceed the order amount",
    ),
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline; rendered by the Flask handler."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        default_status, default_message = ERROR_CATALOG.get(
            error_id, (400, "Request could not be processed")
        )
        self.error_id = error_id
        self.http_status = http_status or default_status
        self.message = message or default_message
