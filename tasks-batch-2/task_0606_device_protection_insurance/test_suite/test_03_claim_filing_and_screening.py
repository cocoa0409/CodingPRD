"""Claim filing validations, fraud screening velocity, and the screen->block cascade.

Covers difficulty rules dual_variant_calc (fraud velocity), transitive_cascade
(screen-block depth 3), boundary_precision_check (velocity at 2), cross_entity_state_dependency
(screen requires active enrollment), and corner validations/errors instances.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
)
from test_helpers import fixtures as fx


def _fraud_screen_for(api, headers, claim_id):
    data, _ = fx._list(api.list_fraud_screens(headers, params={"claim_id": claim_id}))
    return data[0]


# --------------------------------------------------------------------------
# Corner: validations / errors — claim filing
# --------------------------------------------------------------------------
def test_theft_claim_missing_police_report_rejected(api, admin_headers):
    """PRD 3.4: "The `police_report_number` is required and must be non-empty when
    `peril` is `THEFT`, and is ignored for `CRACKED` and `LOST`; a missing theft report
    is rejected with `ERR_POLICE_REPORT_REQUIRED`."

    Design: Corner/validations/theft_claim_missing_police_report_returns_error
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-CN-15")
    resp = api.create_claim({
        "enrollment_id": base["enrollment"]["id"],
        "peril": "THEFT",
        "incident_at": "2026-05-10T00:00:00Z",
    }, admin_headers)
    validate_error(resp, ApiErrorId.ERR_POLICE_REPORT_REQUIRED.value, 422)


def test_claim_incident_before_enrollment_rejected(api, admin_headers):
    """PRD 3.4: "The `incident_at` must fall strictly after the enrollment's
    `enrolled_at` and at or before the current logical clock; an incident before
    activation or in the future is rejected with `ERR_INCIDENT_OUT_OF_WINDOW`."

    Design: Corner/validations/claim_incident_before_enrollment_returns_out_of_window
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-CN-16")
    resp = api.create_claim({
        "enrollment_id": base["enrollment"]["id"],
        "peril": "CRACKED",
        "incident_at": "2026-01-01T00:00:00Z",
    }, admin_headers)
    validate_error(resp, ApiErrorId.ERR_INCIDENT_OUT_OF_WINDOW.value, 422)


def test_second_open_claim_rejected(api, admin_headers):
    """PRD 3.4: "The enrollment must also have no existing non-terminal claim — that is,
    `open_claim_id` must be null — or the submission is rejected with
    `ERR_OPEN_CLAIM_EXISTS`."

    Design: Corner/validations/open_claim_exists_blocks_second_claim
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-CN-17")
    enr = base["enrollment"]
    fx.submit_claim(enr["id"], peril="CRACKED", incident_at="2026-05-01T00:00:00Z")
    resp = api.create_claim({
        "enrollment_id": enr["id"], "peril": "CRACKED", "incident_at": "2026-05-10T00:00:00Z",
    }, admin_headers)
    validate_error(resp, ApiErrorId.ERR_OPEN_CLAIM_EXISTS.value, 409)


def test_claim_on_nonexistent_enrollment_not_found(api, admin_headers):
    """PRD 2.7: "The first identifier that does not resolve to an existing resource
    causes the request to be rejected immediately with `ERR_NOT_FOUND`, before any
    later identifier or business rule is evaluated."

    Design: Corner/errors/claim_submit_on_nonexistent_enrollment_returns_not_found
    """
    fx.set_clock()
    resp = api.create_claim({
        "enrollment_id": NON_EXISTENT_UUID, "peril": "CRACKED",
        "incident_at": "2026-05-10T00:00:00Z",
    }, admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


# --------------------------------------------------------------------------
# Boundary precision: velocity at exactly 2 -> REVIEW
# --------------------------------------------------------------------------
def test_velocity_count_two_yields_review(api, admin_headers, adjuster_headers):
    """PRD 3.5: "The outcome follows from the count against two thresholds: if the count
    is at least 3 the outcome is `BLOCK`; otherwise if the count is at least 2 the
    outcome is `REVIEW`; otherwise the outcome is `PASS`."
    PRD 3.5: "If the outcome is `REVIEW` and the customer's `risk_flag` is currently
    `GREEN`, it is raised to `WATCH`".

    Design: Difficulty/boundary_precision_check/velocity_review_threshold_at_exactly_two
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-DV-11", plan_overrides={"annual_claim_limit": 5})
    enr = base["enrollment"]
    fx.submit_screen_deny(enr["id"], peril="CRACKED", incident_at="2026-04-10T00:00:00Z")
    c2 = fx.submit_claim(enr["id"], peril="CRACKED", incident_at="2026-05-10T00:00:00Z")
    validate_success(api.screen_claim(c2["id"], adjuster_headers))
    screen = _fraud_screen_for(api, adjuster_headers, c2["id"])
    assert screen["velocity_count"] == 2, f"expected count 2, got {screen['velocity_count']}"
    assert screen["outcome"] == "REVIEW"
    cust = validate_success(api.get_customer(base["customer"]["id"], admin_headers))
    assert cust["risk_flag"] == "WATCH"


def test_velocity_count_one_yields_pass(api, admin_headers, adjuster_headers):
    """PRD 3.5: "The outcome follows from the count against two thresholds: if the count
    is at least 3 the outcome is `BLOCK`; otherwise if the count is at least 2 the
    outcome is `REVIEW`; otherwise the outcome is `PASS`."

    Design: Difficulty/boundary_precision_check/velocity_review_threshold_at_exactly_two
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-DV-11B", plan_overrides={"annual_claim_limit": 5})
    enr = base["enrollment"]
    c1 = fx.submit_claim(enr["id"], peril="CRACKED", incident_at="2026-05-10T00:00:00Z")
    validate_success(api.screen_claim(c1["id"], adjuster_headers))
    screen = _fraud_screen_for(api, adjuster_headers, c1["id"])
    assert screen["velocity_count"] == 1, f"expected count 1, got {screen['velocity_count']}"
    assert screen["outcome"] == "PASS"


# --------------------------------------------------------------------------
# dual_variant_calc: fraud velocity REVIEW vs BLOCK divergence
# --------------------------------------------------------------------------
def test_fraud_velocity_review_then_block_diverges(api, admin_headers, adjuster_headers):
    """PRD 3.5: "The outcome follows from the count against two thresholds: if the count
    is at least 3 the outcome is `BLOCK`; otherwise if the count is at least 2 the
    outcome is `REVIEW`; otherwise the outcome is `PASS`."
    PRD 3.5: "If the outcome is `BLOCK`, the customer's `risk_flag` is set to `BLOCKED`."

    Design: Difficulty/dual_variant_calc/fraud_velocity_review_vs_block_outcome_diverges
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-DV-2", plan_overrides={"annual_claim_limit": 5})
    enr = base["enrollment"]
    cust_id = base["customer"]["id"]
    fx.submit_screen_deny(enr["id"], peril="CRACKED", incident_at="2026-03-10T00:00:00Z")
    c2 = fx.submit_claim(enr["id"], peril="CRACKED", incident_at="2026-04-10T00:00:00Z")
    validate_success(api.screen_claim(c2["id"], adjuster_headers))
    s2 = _fraud_screen_for(api, adjuster_headers, c2["id"])
    assert s2["outcome"] == "REVIEW" and s2["velocity_count"] == 2
    fx.deny_claim(c2["id"], denial_reason="NO_COVERAGE")
    c3 = fx.submit_claim(enr["id"], peril="CRACKED", incident_at="2026-05-10T00:00:00Z")
    validate_success(api.screen_claim(c3["id"], adjuster_headers))
    s3 = _fraud_screen_for(api, adjuster_headers, c3["id"])
    assert s3["outcome"] == "BLOCK" and s3["velocity_count"] == 3
    cust = validate_success(api.get_customer(cust_id, admin_headers))
    assert cust["risk_flag"] == "BLOCKED"


def test_fraud_velocity_block_sets_customer_blocked(api, admin_headers, adjuster_headers):
    """PRD 3.5: "If the outcome is `BLOCK`, the customer's `risk_flag` is set to
    `BLOCKED`."

    Design: Difficulty/dual_variant_calc/fraud_velocity_review_vs_block_outcome_diverges
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-DV-2B", plan_overrides={"annual_claim_limit": 5})
    enr = base["enrollment"]
    fx.submit_screen_deny(enr["id"], peril="CRACKED", incident_at="2026-03-10T00:00:00Z")
    fx.submit_screen_deny(enr["id"], peril="CRACKED", incident_at="2026-04-10T00:00:00Z")
    c3 = fx.submit_claim(enr["id"], peril="CRACKED", incident_at="2026-05-10T00:00:00Z")
    validate_success(api.screen_claim(c3["id"], adjuster_headers))
    s3 = _fraud_screen_for(api, adjuster_headers, c3["id"])
    assert s3["outcome"] == "BLOCK"
    cust = validate_success(api.get_customer(base["customer"]["id"], admin_headers))
    assert cust["risk_flag"] == "BLOCKED"


# --------------------------------------------------------------------------
# transitive_cascade: screen-block depth 3 (block -> blocked flag -> approve rejected)
# --------------------------------------------------------------------------
def test_screen_block_cascade_blocks_subsequent_approve(api, admin_headers, adjuster_headers):
    """PRD 3.5: "If the outcome is `BLOCK`, the customer's `risk_flag` is set to
    `BLOCKED`."
    PRD 3.6: "the customer's `risk_flag` is not `BLOCKED` (either of these conditions
    failing is rejected with `ERR_FRAUD_BLOCKED`)".

    Design: Difficulty/transitive_cascade/claim_screen_block_cascade_depth3
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-DV-7", plan_overrides={"annual_claim_limit": 5})
    enr = base["enrollment"]
    fx.submit_screen_deny(enr["id"], peril="CRACKED", incident_at="2026-03-10T00:00:00Z")
    fx.submit_screen_deny(enr["id"], peril="CRACKED", incident_at="2026-04-10T00:00:00Z")
    c3 = fx.submit_claim(enr["id"], peril="CRACKED", incident_at="2026-05-10T00:00:00Z")
    validate_success(api.screen_claim(c3["id"], adjuster_headers))
    s3 = _fraud_screen_for(api, adjuster_headers, c3["id"])
    assert s3["outcome"] == "BLOCK"
    cust = validate_success(api.get_customer(base["customer"]["id"], admin_headers))
    assert cust["risk_flag"] == "BLOCKED"
    enr_v = fx.current_enrollment_version(enr["id"])
    resp = api.approve_claim(c3["id"], {"expected_enrollment_version": enr_v}, adjuster_headers)
    validate_error(resp, ApiErrorId.ERR_FRAUD_BLOCKED.value, 409)


def test_screen_block_sets_blocked_flag_cascade(api, admin_headers, adjuster_headers):
    """PRD 3.5: "The outcome cascades onto the customer's posture. If the outcome is
    `BLOCK`, the customer's `risk_flag` is set to `BLOCKED`."

    Design: Difficulty/transitive_cascade/claim_screen_block_cascade_depth3
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-DV-7B", plan_overrides={"annual_claim_limit": 5})
    enr = base["enrollment"]
    fx.submit_screen_deny(enr["id"], peril="CRACKED", incident_at="2026-03-10T00:00:00Z")
    fx.submit_screen_deny(enr["id"], peril="CRACKED", incident_at="2026-04-10T00:00:00Z")
    c3 = fx.submit_claim(enr["id"], peril="CRACKED", incident_at="2026-05-10T00:00:00Z")
    validate_success(api.screen_claim(c3["id"], adjuster_headers))
    cust = validate_success(api.get_customer(base["customer"]["id"], admin_headers))
    assert cust["risk_flag"] == "BLOCKED"
