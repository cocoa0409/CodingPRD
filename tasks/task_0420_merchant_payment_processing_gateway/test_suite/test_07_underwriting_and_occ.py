"""Merchant underwriting lifecycle, the risk-band policy guard, batch re-settle state guard,
and optimistic concurrency on settle.

Covers difficulty queue (cross_entity_state_dependency batch-settle state guard) and corner
merchant-state-machine + OCC + risk-policy instances.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    set_clock,
    create_flat_plan, create_approved_merchant, create_captured_charge,
    open_and_settle_batch, register_merchant, get_open_risk_review_id,
    TEST_USERS,
)

OPERATOR = TEST_USERS["platform_operator_headers"]
OFFICER = TEST_USERS["underwriting_officer_headers"]


def test_second_settle_on_settled_batch_rejected(api):
    """PRD §3.7: "Settle is permitted only while the batch's `batch_status` is `OPEN`".
    PRD §2.9: "Every action endpoint that drives a state machine first checks that the target
    resource is in a state from which the requested transition is defined; if it is not, the
    request is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/batch_settle_requires_merchant_not_rejected_and_charges_batched
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    version = merchant["version"]
    create_captured_charge(merchant["id"], auth_amount_cents=10000)
    batch, version_after_settle = open_and_settle_batch(merchant["id"], version, business_date="2026-01-01")
    # second settle, even with a fresh (correct) merchant version, fails on batch state.
    resp = api.settle_batch(batch["id"], {"expected_merchant_version": version_after_settle}, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_settle_on_funded_batch_rejected(api):
    """PRD §3.7: "Settle is permitted only while the batch's `batch_status` is `OPEN`".
    PRD §3.7: "Funding the batch advances it from `SETTLED` to the terminal `FUNDED`."

    Design: Difficulty/cross_entity_state_dependency/batch_settle_requires_merchant_not_rejected_and_charges_batched
    """
    from test_helpers import advance_clock
    set_clock("2026-01-01T00:00:00Z")
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    version = merchant["version"]
    create_captured_charge(merchant["id"], auth_amount_cents=10000)
    batch, version_after_settle = open_and_settle_batch(merchant["id"], version, business_date="2026-01-01")
    advance_clock("2026-01-03T00:00:00Z")
    validate_success(api.fund_batch(batch["id"], {}, OPERATOR))
    # batch is now FUNDED (terminal); settle is undefined from that state.
    resp = api.settle_batch(batch["id"], {"expected_merchant_version": version_after_settle}, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_settle_with_stale_merchant_version_rejected(api):
    """PRD §2.10: "If the merchant's current `version` no longer equals the supplied
    `expected_merchant_version` — because the merchant was re-underwritten or otherwise mutated
    since the operator read it — the settle is rejected with `ERR_STALE_MERCHANT_VERSION`
    (HTTP 412)".

    Design: Corner/Cross-Cutting Complexity Layers/corner_occ_stale_merchant_version_on_settle
    """
    set_clock("2026-01-01T00:00:00Z")
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    stale_version = merchant["version"]
    create_captured_charge(merchant["id"], auth_amount_cents=10000)
    batch = validate_success(api.create_settlement_batch(merchant["id"], {"business_date": "2026-01-01"}, OPERATOR), expected_status=201)
    # suspend + reinstate bump the merchant version, making the captured version stale.
    validate_success(api.suspend_merchant(merchant["id"], {}, OFFICER))
    validate_success(api.reinstate_merchant(merchant["id"], {}, OFFICER))
    resp = api.settle_batch(batch["id"], {"expected_merchant_version": stale_version}, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_STALE_MERCHANT_VERSION)


def test_merchant_version_increments_on_each_write(api):
    """PRD §2.4: "a `version` integer that starts at its initial value and increments by one on
    every mutation of the resource."
    PRD §3.2: "each of suspension and reinstatement increments the merchant's `version` by
    one."

    Design: Corner/Cross-Cutting Complexity Layers/corner_occ_version_increments_on_each_write
    """
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    version_after_approve = merchant["version"]
    suspended = validate_success(api.suspend_merchant(merchant["id"], {}, OFFICER))
    assert suspended["version"] == version_after_approve + 1


# --- Corner: merchant state machine ---

def test_reject_open_review_moves_merchant_to_rejected(api):
    """PRD §3.2: "Rejection drives the merchant from `PENDING_REVIEW` to `REJECTED`, which is a
    terminal onboarding state".

    Design: Corner/State Machines/corner_merchant_reject_initial_to_terminal
    """
    plan = create_flat_plan()
    merchant = register_merchant(plan["id"], legal_name="Reject Co")
    review_id = get_open_risk_review_id(merchant["id"])
    rejected = validate_success(api.reject_risk_review(merchant["id"], review_id, {"notes": "incomplete docs"}, OFFICER))
    assert rejected["onboarding_status"] == "REJECTED"


def test_suspend_then_reinstate_returns_to_approved(api):
    """PRD §3.2: "an officer may suspend a merchant, driving it from `APPROVED` to `SUSPENDED`
    (permitted only from `APPROVED`), and may later reinstate it, driving it from `SUSPENDED`
    back to `APPROVED` (permitted only from `SUSPENDED`); each of suspension and reinstatement
    increments the merchant's `version` by one."

    Design: Corner/State Machines/corner_merchant_suspend_reinstate_cycle
    """
    plan = create_flat_plan()
    merchant, _ = create_approved_merchant(fee_plan_id=plan["id"], assigned_risk_band="LOW")
    suspended = validate_success(api.suspend_merchant(merchant["id"], {}, OFFICER))
    v_after_suspend = suspended["version"]
    reinstated = validate_success(api.reinstate_merchant(merchant["id"], {}, OFFICER))
    assert reinstated["onboarding_status"] == "APPROVED"
    assert reinstated["version"] == v_after_suspend + 1


def test_suspend_on_rejected_merchant_rejected(api):
    """PRD §3.2: "an officer may suspend a merchant, driving it from `APPROVED` to `SUSPENDED`
    (permitted only from `APPROVED`)".
    PRD §2.9: "Every action endpoint that drives a state machine first checks that the target
    resource is in a state from which the requested transition is defined; if it is not, the
    request is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/State Machines/corner_merchant_reject_terminal_lockdown
    """
    plan = create_flat_plan()
    merchant = register_merchant(plan["id"], legal_name="Term Co")
    review_id = get_open_risk_review_id(merchant["id"])
    validate_success(api.reject_risk_review(merchant["id"], review_id, {}, OFFICER))
    resp = api.suspend_merchant(merchant["id"], {}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_high_risk_mcc_approved_with_non_high_band_rejected(api):
    """PRD §3.2: "When the merchant's `mcc` is one of these high-risk codes, the officer must
    assign the `HIGH` band; approving such a merchant with an `assigned_risk_band` other than
    `HIGH` is rejected with `ERR_RISK_BAND_POLICY_VIOLATION` (HTTP 422)."

    Design: Corner/RBAC/corner_high_risk_mcc_band_policy_violation
    """
    plan = create_flat_plan()
    merchant = register_merchant(plan["id"], legal_name="HR Co", mcc="7995")
    review_id = get_open_risk_review_id(merchant["id"])
    resp = api.approve_risk_review(merchant["id"], review_id, {"assigned_risk_band": "LOW"}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_RISK_BAND_POLICY_VIOLATION)
