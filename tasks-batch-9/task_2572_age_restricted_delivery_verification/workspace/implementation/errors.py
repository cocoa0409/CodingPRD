"""Complete error catalogue (PRD section 5) -- 60 identifiers with their HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
        self.http_status = ERROR_STATUS.get(error_id, 400)


ERROR_STATUS = {
    # --- authentication / authorisation ---
    "ERR_MISSING_AUTH_HEADER": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN_RESOURCE_SCOPE": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- existence, one per entity ---
    "ERR_JURISDICTION_NOT_FOUND": 404,
    "ERR_POLICY_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_ORDER_LINE_NOT_FOUND": 404,
    "ERR_PARTNER_NOT_FOUND": 404,
    "ERR_COURIER_NOT_FOUND": 404,
    "ERR_CERTIFICATION_NOT_FOUND": 404,
    "ERR_ATTEMPT_NOT_FOUND": 404,
    "ERR_SHOPPER_TEST_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    # --- shape / cross-field / concurrency ---
    "ERR_VALIDATION": 400,
    "ERR_INCONSISTENT_FIELDS": 422,
    "ERR_STALE_CUSTOMER_VERSION": 412,
    "ERR_STALE_CASE_VERSION": 412,
    # --- state preconditions ---
    "ERR_INVALID_ORDER_STATE": 409,
    "ERR_INVALID_ATTEMPT_STATE": 409,
    "ERR_INVALID_CASE_STATE": 409,
    "ERR_INVALID_PLAN_STATE": 409,
    "ERR_INVALID_CERTIFICATION_STATE": 409,
    "ERR_ORDER_HAS_NO_LINES": 409,
    "ERR_CLOCK_REWIND": 409,
    # --- policy resolution and jurisdictional permissibility ---
    "ERR_NO_EFFECTIVE_POLICY": 422,
    "ERR_DELIVERY_PROHIBITED_IN_JURISDICTION": 422,
    "ERR_DRY_JURISDICTION_PROHIBITED": 422,
    "ERR_PERMIT_REQUIRED": 422,
    # --- partner / courier authority ---
    "ERR_PARTNER_SUSPENDED": 422,
    "ERR_COURIER_PARTNER_MISMATCH": 422,
    "ERR_COURIER_NOT_CERTIFIED": 422,
    "ERR_CERTIFICATION_MISSING_FOR_RESTRICTION": 422,
    "ERR_TRAINING_SCORE_TOO_LOW": 422,
    # --- door-side identification ---
    "ERR_DOCUMENT_TYPE_NOT_ACCEPTABLE": 422,
    "ERR_SCAN_REQUIRED": 422,
    "ERR_DOCUMENT_EXPIRED": 422,
    "ERR_RECIPIENT_IDENTITY_MISMATCH": 422,
    "ERR_REFUSAL_REASON_NOT_ALLOWED": 422,
    # --- purchaser eligibility ---
    "ERR_ATTESTATION_REQUIRED": 422,
    "ERR_CUSTOMER_DELIVERY_BLOCKED": 422,
    "ERR_IDENTITY_PREVERIFICATION_REQUIRED": 422,
    "ERR_PURCHASER_UNDERAGE": 422,
    # --- capture completeness ---
    "ERR_CAPTURE_INCOMPLETE": 422,
    # --- temporal admissibility ---
    "ERR_OUTSIDE_RESTRICTED_HOURS": 422,
    "ERR_SCHEDULED_TIME_IN_PAST": 422,
    "ERR_RESPONSE_DUE_NOT_FUTURE": 422,
    "ERR_TRAINING_STALE": 422,
    # --- interval occupation ---
    "ERR_COURIER_SLOT_CONFLICT": 409,
    "ERR_POLICY_PERIOD_OVERLAP": 409,
    # --- structural constraints ---
    "ERR_DUPLICATE_CODE": 409,
    "ERR_DUPLICATE_CAPTURE_KIND": 409,
    "ERR_CASE_SUBJECT_INVALID": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    # --- settlement and quantity ceilings ---
    "ERR_RESTOCK_NOT_CONFIRMED": 422,
    "ERR_ORDER_UNIT_LIMIT_EXCEEDED": 422,
    "ERR_WINDOW_UNIT_LIMIT_EXCEEDED": 422,
}

DEFAULT_MESSAGES = {
    "ERR_MISSING_AUTH_HEADER": "X-User-ID and X-User-Role headers are required",
    "ERR_UNAUTHORIZED": "role is not permitted to call this endpoint",
    "ERR_FORBIDDEN_RESOURCE_SCOPE": "caller may not act on a resource owned by another principal",
    "ERR_SEGREGATION_OF_DUTIES": "the substantiating officer may not review or verify the plan",
    "ERR_JURISDICTION_NOT_FOUND": "jurisdiction not found",
    "ERR_POLICY_NOT_FOUND": "restriction policy not found",
    "ERR_PRODUCT_NOT_FOUND": "product not found",
    "ERR_CUSTOMER_NOT_FOUND": "customer not found",
    "ERR_ORDER_NOT_FOUND": "order not found",
    "ERR_ORDER_LINE_NOT_FOUND": "order line not found",
    "ERR_PARTNER_NOT_FOUND": "delivery partner not found",
    "ERR_COURIER_NOT_FOUND": "courier not found",
    "ERR_CERTIFICATION_NOT_FOUND": "courier certification not found",
    "ERR_ATTEMPT_NOT_FOUND": "delivery attempt not found",
    "ERR_SHOPPER_TEST_NOT_FOUND": "secret shopper test not found",
    "ERR_CASE_NOT_FOUND": "violation case not found",
    "ERR_PLAN_NOT_FOUND": "corrective action plan not found",
    "ERR_VALIDATION": "request shape is invalid",
    "ERR_INCONSISTENT_FIELDS": "fields in the request body contradict one another",
    "ERR_STALE_CUSTOMER_VERSION": "expected_customer_version does not match the stored customer version",
    "ERR_STALE_CASE_VERSION": "expected_violation_case_version does not match the stored case version",
    "ERR_INVALID_ORDER_STATE": "order is not in a state that permits this transition",
    "ERR_INVALID_ATTEMPT_STATE": "delivery attempt is not in a state that permits this transition",
    "ERR_INVALID_CASE_STATE": "violation case is not in a state that permits this transition",
    "ERR_INVALID_PLAN_STATE": "corrective action plan is not in a state that permits this transition",
    "ERR_INVALID_CERTIFICATION_STATE": "certification is not in a state that permits this transition",
    "ERR_ORDER_HAS_NO_LINES": "order has no lines and cannot be submitted",
    "ERR_CLOCK_REWIND": "the logical clock may never move backwards",
    "ERR_NO_EFFECTIVE_POLICY": "no effective restriction policy governs this restriction class",
    "ERR_DELIVERY_PROHIBITED_IN_JURISDICTION": "delivery of this restriction class is prohibited in the jurisdiction",
    "ERR_DRY_JURISDICTION_PROHIBITED": "alcohol delivery is prohibited in a dry jurisdiction",
    "ERR_PERMIT_REQUIRED": "a permit is required to deliver into a damp jurisdiction",
    "ERR_PARTNER_SUSPENDED": "the delivery partner posture is SUSPENDED",
    "ERR_COURIER_PARTNER_MISMATCH": "the courier is not employed by the order's delivery partner",
    "ERR_COURIER_NOT_CERTIFIED": "the courier is not certified",
    "ERR_CERTIFICATION_MISSING_FOR_RESTRICTION": "the courier holds no active certification for a restriction class on this order",
    "ERR_TRAINING_SCORE_TOO_LOW": "training score is below the required bar",
    "ERR_DOCUMENT_TYPE_NOT_ACCEPTABLE": "the presented document type is not acceptable under every governing policy",
    "ERR_SCAN_REQUIRED": "a physical scan of the document is required",
    "ERR_DOCUMENT_EXPIRED": "the presented document has expired",
    "ERR_RECIPIENT_IDENTITY_MISMATCH": "the scanned date of birth does not match the attested purchaser",
    "ERR_REFUSAL_REASON_NOT_ALLOWED": "the refusal reason is not permitted from the attempt's current state",
    "ERR_ATTESTATION_REQUIRED": "the purchaser has not completed age attestation",
    "ERR_CUSTOMER_DELIVERY_BLOCKED": "the purchaser is blocked from restricted delivery",
    "ERR_IDENTITY_PREVERIFICATION_REQUIRED": "the purchaser has no valid identity check",
    "ERR_PURCHASER_UNDERAGE": "the purchaser is below the minimum age required by policy",
    "ERR_CAPTURE_INCOMPLETE": "the mandatory evidence captures are not all present",
    "ERR_OUTSIDE_RESTRICTED_HOURS": "the local delivery minute falls outside the permitted window",
    "ERR_SCHEDULED_TIME_IN_PAST": "scheduled_delivery_at must lie strictly later than now",
    "ERR_RESPONSE_DUE_NOT_FUTURE": "response_due_at must lie strictly later than now",
    "ERR_TRAINING_STALE": "the training completion date is stale",
    "ERR_COURIER_SLOT_CONFLICT": "the courier already occupies an overlapping dwell interval",
    "ERR_POLICY_PERIOD_OVERLAP": "the effective period overlaps an existing policy for the same class",
    "ERR_DUPLICATE_CODE": "a uniquely constrained value is already in use",
    "ERR_DUPLICATE_CAPTURE_KIND": "a capture of that kind already exists for this attempt",
    "ERR_CASE_SUBJECT_INVALID": "exactly one of delivery_attempt_id or secret_shopper_test_id must be supplied",
    "ERR_REVISION_LIMIT_REACHED": "the plan has exhausted its permitted revision rounds",
    "ERR_RESTOCK_NOT_CONFIRMED": "restock_confirmed must be true to settle the return",
    "ERR_ORDER_UNIT_LIMIT_EXCEEDED": "the per-order restricted unit ceiling is exceeded",
    "ERR_WINDOW_UNIT_LIMIT_EXCEEDED": "the rolling-window restricted unit ceiling is exceeded",
}
