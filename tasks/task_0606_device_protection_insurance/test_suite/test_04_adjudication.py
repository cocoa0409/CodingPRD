"""Claim adjudication: deductible quoting, approval OCC, denial cascade, priority pairs.

Covers difficulty rules combinatorial_formula (deductible order), priority_pair_validation_conflict,
cross_cutting OCC, consistency_model, and corner calculations/state_machines instances.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
)
from test_helpers import fixtures as fx


def _raise_to_watch(api, admin_headers, adjuster_headers, enr, cust_id):
    """Two DENIED claims close together so the second screen yields REVIEW -> WATCH on a
    GREEN customer.

    Uses the documented velocity rule: count>=2 -> REVIEW; REVIEW from GREEN -> WATCH.
    The two incidents are placed early (2026-01-20 and 2026-02-10) so they fall within each
    other's 90-day window (the second screens at velocity 2 -> REVIEW), yet age out of the
    90-day window of a later THEFT incident (2026-05-20, window opens 2026-02-19) so that the
    THEFT claim screens at velocity 1 -> PASS and the customer remains WATCH at approval.
    """
    fx.submit_screen_deny(enr["id"], peril="CRACKED", incident_at="2026-01-20T00:00:00Z")
    c2 = fx.submit_claim(enr["id"], peril="CRACKED", incident_at="2026-02-10T00:00:00Z")
    validate_success(api.screen_claim(c2["id"], adjuster_headers))
    fx.deny_claim(c2["id"], denial_reason="NO_COVERAGE")
    cust = validate_success(api.get_customer(cust_id, admin_headers))
    assert cust["risk_flag"] == "WATCH"


# --------------------------------------------------------------------------
# Corner: deductible CRACKED + GREEN -> base only
# --------------------------------------------------------------------------
def test_deductible_cracked_green_base_only(api, admin_headers, adjuster_headers):
    """PRD 3.6: "for a `CRACKED` claim the tier base equals the plan's
    `base_deductible_cents` with no multiplier applied".
    PRD 3.6: "for a `GREEN` customer the surcharge is zero ... The final
    `deductible_cents` is the tier base plus the surcharge."

    Design: Corner/calculations/deductible_cracked_green_base_only
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-CN-12")
    enr = base["enrollment"]
    cl = fx.submit_claim(enr["id"], peril="CRACKED", incident_at="2026-05-10T00:00:00Z")
    fx.screen_claim(cl["id"])
    enr_v = fx.current_enrollment_version(enr["id"])
    approved = validate_success(api.approve_claim(
        cl["id"], {"expected_enrollment_version": enr_v}, adjuster_headers))
    assert approved["deductible_cents"] == 10000, \
        f"expected 10000, got {approved['deductible_cents']}"


# --------------------------------------------------------------------------
# combinatorial_formula: loss tier then WATCH surcharge order
# --------------------------------------------------------------------------
def test_theft_watch_deductible_tier_then_surcharge(api, admin_headers, adjuster_headers):
    """PRD 3.6: "for a `LOST` or `THEFT` claim the tier base is the plan's
    `base_deductible_cents` multiplied by the plan's `loss_deductible_multiplier_bps`
    and divided by 10000, rounded half up to whole cents."
    PRD 3.6: "if the flag is `WATCH`, the surcharge is the tier base multiplied by 2500
    basis points and divided by 10000 ... rounded half up to whole cents".

    Design: Difficulty/combinatorial_formula/deductible_loss_tier_then_watch_surcharge_order
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-DV-3", plan_overrides={"annual_claim_limit": 5})
    enr = base["enrollment"]
    _raise_to_watch(api, admin_headers, adjuster_headers, enr, base["customer"]["id"])
    cl = fx.submit_claim(enr["id"], peril="THEFT", incident_at="2026-05-20T00:00:00Z",
                         police_report_number="PR-77")
    fx.screen_claim(cl["id"])
    enr_v = fx.current_enrollment_version(enr["id"])
    approved = validate_success(api.approve_claim(
        cl["id"], {"expected_enrollment_version": enr_v}, adjuster_headers))
    # tier_base = 10000 * 15000/10000 = 15000; surcharge = 15000 * 2500/10000 = 3750; total 18750
    assert approved["deductible_cents"] == 18750, \
        f"expected 18750, got {approved['deductible_cents']}"


def test_watch_customer_at_approval_drives_surcharge(api, admin_headers, adjuster_headers):
    """PRD 2.9: "A `WATCH` posture raises the deductible a customer is quoted".
    PRD 3.6: "a risk surcharge keyed on the customer's `risk_flag` at approval time is
    added: if the flag is `WATCH`, the surcharge is the tier base multiplied by 2500
    basis points and divided by 10000".

    Design: Difficulty/combinatorial_formula/deductible_loss_tier_then_watch_surcharge_order
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-DV-3B", plan_overrides={"annual_claim_limit": 5})
    enr = base["enrollment"]
    _raise_to_watch(api, admin_headers, adjuster_headers, enr, base["customer"]["id"])
    cl = fx.submit_claim(enr["id"], peril="THEFT", incident_at="2026-05-20T00:00:00Z",
                         police_report_number="PR-78")
    fx.screen_claim(cl["id"])
    enr_v = fx.current_enrollment_version(enr["id"])
    approved = validate_success(api.approve_claim(
        cl["id"], {"expected_enrollment_version": enr_v}, adjuster_headers))
    assert approved["deductible_cents"] == 18750


# --------------------------------------------------------------------------
# consistency_model: deductible visible immediately in approve response
# --------------------------------------------------------------------------
def test_approve_response_carries_deductible_immediately(api, admin_headers, adjuster_headers):
    """PRD 3.6: "On approval the system computes `deductible_cents`, sets the status to
    `APPROVED`".
    PRD 2.6: "every such cascade settles immediately and in full ... there is no
    deferred reconciliation."

    Design: Corner/consistency_model/immediate_approval_visible_in_same_response
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-CN-26")
    enr = base["enrollment"]
    cl = fx.submit_claim(enr["id"], peril="CRACKED", incident_at="2026-05-10T00:00:00Z")
    fx.screen_claim(cl["id"])
    enr_v = fx.current_enrollment_version(enr["id"])
    approved = validate_success(api.approve_claim(
        cl["id"], {"expected_enrollment_version": enr_v}, adjuster_headers))
    assert approved["deductible_cents"] == 10000
    assert approved["status"] == "APPROVED"


# --------------------------------------------------------------------------
# Corner: state_machine invalid transition / denial cascade
# --------------------------------------------------------------------------
def test_approve_submitted_claim_invalid_state(api, admin_headers, adjuster_headers):
    """PRD 3.6: "From `UNDER_REVIEW`, a `ClaimsAdjuster` either approves or denies the
    claim."
    PRD 3.2: "Any attempt to drive a state transition from a status where it is not
    defined is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/approve_from_submitted_returns_invalid_state
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-CN-8")
    enr = base["enrollment"]
    cl = fx.submit_claim(enr["id"], peril="CRACKED", incident_at="2026-05-10T00:00:00Z")
    enr_v = fx.current_enrollment_version(enr["id"])
    resp = api.approve_claim(cl["id"], {"expected_enrollment_version": enr_v}, adjuster_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_deny_fraud_blocks_customer_and_clears_open_claim(api, admin_headers, adjuster_headers):
    """PRD 3.6: "On denial the status becomes `DENIED` with the supplied `denial_reason`
    recorded, the enrollment's `open_claim_id` is cleared, and the claim's `version`
    increments by one. As a cascade, when the `denial_reason` is `FRAUD` the customer's
    `risk_flag` is set to `BLOCKED`."

    Design: Corner/state_machines/deny_fraud_blocks_customer_cascade
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-CN-10")
    enr = base["enrollment"]
    cl = fx.submit_claim(enr["id"], peril="CRACKED", incident_at="2026-05-10T00:00:00Z")
    fx.screen_claim(cl["id"])
    denied = validate_success(api.deny_claim(cl["id"], {"denial_reason": "FRAUD"}, adjuster_headers))
    assert denied["status"] == "DENIED" and denied["denial_reason"] == "FRAUD"
    cust = validate_success(api.get_customer(base["customer"]["id"], admin_headers))
    assert cust["risk_flag"] == "BLOCKED"
    enr_after = validate_success(api.get_enrollment(enr["id"], admin_headers))
    assert enr_after["open_claim_id"] is None


# --------------------------------------------------------------------------
# priority_pair_validation_conflict
# --------------------------------------------------------------------------
def test_fraud_blocked_beats_claim_limit(api, admin_headers, adjuster_headers, logistics_headers):
    """PRD 3.6: "These checks are evaluated in order — the fraud/risk gate first, then
    the annual-limit gate, then the stale-version gate".
    PRD 3.6: "the customer's `risk_flag` is not `BLOCKED` (either of these conditions
    failing is rejected with `ERR_FRAUD_BLOCKED`)".

    Design: Difficulty/priority_pair_validation_conflict/fraud_blocked_beats_claim_limit
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-DV-9", plan_overrides={
        "code": "PLAN_LIM1", "annual_claim_limit": 1})
    enr = base["enrollment"]
    # First claim approved + repair-completed -> consumes the annual_claim_limit=1 allowance.
    c1 = fx.submit_claim(enr["id"], peril="CRACKED", incident_at="2026-03-10T00:00:00Z")
    fx.screen_claim(c1["id"])
    fx.approve_claim(c1["id"], enr["id"])
    fx.route_claim(c1["id"], repair_cost_cents=20000)
    ro = fx.repair_order_for_claim(c1["id"])
    validate_success(api.complete_repair_order(ro["id"], logistics_headers))
    # Two more denied in-window claims so the customer is BLOCKED by velocity (count reaches 3).
    fx.submit_screen_deny(enr["id"], peril="CRACKED", incident_at="2026-03-20T00:00:00Z")
    fx.submit_screen_deny(enr["id"], peril="CRACKED", incident_at="2026-04-10T00:00:00Z")
    c4 = fx.submit_claim(enr["id"], peril="CRACKED", incident_at="2026-05-10T00:00:00Z")
    validate_success(api.screen_claim(c4["id"], adjuster_headers))
    cust = validate_success(api.get_customer(base["customer"]["id"], admin_headers))
    assert cust["risk_flag"] == "BLOCKED"
    enr_v = fx.current_enrollment_version(enr["id"])
    resp = api.approve_claim(c4["id"], {"expected_enrollment_version": enr_v}, adjuster_headers)
    validate_error(resp, ApiErrorId.ERR_FRAUD_BLOCKED.value, 409)


def test_claim_limit_exceeded_when_not_blocked(api, admin_headers, adjuster_headers, logistics_headers):
    """PRD 3.6: "the enrollment's count of approved-or-beyond claims in the trailing
    twelve months is strictly below the plan's `annual_claim_limit` (a breach is rejected
    with `ERR_CLAIM_LIMIT_EXCEEDED`)".

    Design: Difficulty/priority_pair_validation_conflict/fraud_blocked_beats_claim_limit
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-DV-9B", plan_overrides={
        "code": "PLAN_LIM1B", "annual_claim_limit": 1})
    enr = base["enrollment"]
    # Consume the single allowance with an approved+fulfilled claim.
    c1 = fx.submit_claim(enr["id"], peril="CRACKED", incident_at="2026-05-01T00:00:00Z")
    fx.screen_claim(c1["id"])
    fx.approve_claim(c1["id"], enr["id"])
    fx.route_claim(c1["id"], repair_cost_cents=20000)
    ro = fx.repair_order_for_claim(c1["id"])
    validate_success(api.complete_repair_order(ro["id"], logistics_headers))
    # Second claim: single in-window claim -> PASS (GREEN customer), only the limit gate fails.
    c2 = fx.submit_claim(enr["id"], peril="CRACKED", incident_at="2026-05-10T00:00:00Z")
    validate_success(api.screen_claim(c2["id"], adjuster_headers))
    cust = validate_success(api.get_customer(base["customer"]["id"], admin_headers))
    assert cust["risk_flag"] != "BLOCKED", "customer must not be fraud-blocked for this test"
    enr_v = fx.current_enrollment_version(enr["id"])
    resp = api.approve_claim(c2["id"], {"expected_enrollment_version": enr_v}, adjuster_headers)
    validate_error(resp, ApiErrorId.ERR_CLAIM_LIMIT_EXCEEDED.value, 409)


# --------------------------------------------------------------------------
# OCC on approve
# --------------------------------------------------------------------------
def test_approve_correct_version_succeeds_and_bumps_enrollment(api, admin_headers, adjuster_headers):
    """PRD 2.5: "The approval request must carry `expected_enrollment_version` matching
    the target enrollment's current `version`. Approval debits the enrollment's annual
    claim allowance and increments `Enrollment.version`".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_enrollment_version_approves_and_bumps
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-CN-22")
    enr = base["enrollment"]
    cl = fx.submit_claim(enr["id"], peril="CRACKED", incident_at="2026-05-10T00:00:00Z")
    fx.screen_claim(cl["id"])
    enr_v = fx.current_enrollment_version(enr["id"])
    approved = validate_success(api.approve_claim(
        cl["id"], {"expected_enrollment_version": enr_v}, adjuster_headers))
    assert approved["status"] == "APPROVED"
    after = validate_success(api.get_enrollment(enr["id"], admin_headers))
    assert after["version"] == enr_v + 1, f"enrollment version must bump to {enr_v + 1}"


def test_approve_stale_enrollment_version_rejected(api, admin_headers, adjuster_headers):
    """PRD 2.5: "if another writer has advanced the enrollment's version since the client
    last read it, the approval is rejected with `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412)
    on the stale-version check".
    PRD 3.3: "the pay request must carry `expected_enrollment_version` ... On success the
    invoice moves to `PAID`, the enrollment's `premium_paid_through_cycle` is recomputed
    ... and the enrollment's `version` increments by one."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_enrollment_version_rejected
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-CN-23")
    enr = base["enrollment"]
    cl = fx.submit_claim(enr["id"], peril="CRACKED", incident_at="2026-05-10T00:00:00Z")
    fx.screen_claim(cl["id"])
    stale_v = fx.current_enrollment_version(enr["id"])
    inv = fx.issue_invoice(enr["id"], 0)
    fx.pay_invoice(inv["id"], enr["id"])  # bumps enrollment version, making stale_v stale
    resp = api.approve_claim(cl["id"], {"expected_enrollment_version": stale_v}, adjuster_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_ENROLLMENT_VERSION.value, 412)
    after = validate_success(api.get_claim(cl["id"], adjuster_headers))
    assert after["status"] == "UNDER_REVIEW", "claim must stay UNDER_REVIEW"
