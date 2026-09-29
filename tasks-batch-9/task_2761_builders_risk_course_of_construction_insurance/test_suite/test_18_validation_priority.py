"""Two rules violated by one request: which refusal the caller is entitled to."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import api_client
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_loss_payment
from test_helpers.factories import create_loss_payment_payload, loss_item

NARROW_TRANSIT_PART_PLAN = (
    ("IN_TRANSIT", 20000000),
    ("MATERIALS_ON_SITE", 1000000000),
)


def _account_with_stale_allocation():
    """Claim B's allocation is stale: a sibling claim's payment ate the bucket."""
    account = fx.in_force_account(parts=NARROW_TRANSIT_PART_PLAN)
    foreign = fx.draft_account(project_overrides={"name": "Rivermill Depot"})

    claim_a = fx.adjusted_claim(
        account, [loss_item("IN_TRANSIT", 20000000)],
        adjustment_basis="ACTUAL_LOSS", peril="THEFT",
        loss_date="2026-11-20T00:00:00Z")
    assert claim_a["indemnity_cents"] == 10000000, claim_a["indemnity_cents"]

    claim_b = fx.adjusted_claim(
        account, [loss_item("IN_TRANSIT", 25000000)],
        adjustment_basis="ACTUAL_LOSS", peril="FIRE",
        loss_date="2026-12-04T00:00:00Z")
    assert claim_b["indemnity_cents"] == 15000000, claim_b["indemnity_cents"]

    fx.issue_payment(account, claim_a, "IN_TRANSIT", 10000000)
    claim_b = get_success_data(api_client.get_claim(claim_b["id"], fx.CA))
    return account, claim_b, foreign.owner_interest


def _payment_attempt(claim, payee_interest_id, amount_cents):
    payload = create_loss_payment_payload(
        claim["id"], claim["version"], payee_interest_id,
        "IN_TRANSIT", amount_cents)
    return api_client.create_loss_payment(payload, fx.CA)


def test_a_payee_from_another_policy_outranks_the_bucket_availability_ceiling():
    """payee_interest_id must reference an interest whose policy_id equals the
    claim's policy_id, and the PRD says that refusal lands before any money
    check runs at all. The request violates both rules and must surface
    ERR_PAYEE_NOT_ON_POLICY.

    Design: Difficulty/priority_pair_validation_conflict/payee_referential_check_outranks_reserve_ceiling_and_rejects_payment
    """
    _, claim_b, foreign_interest = _account_with_stale_allocation()

    both_violated = _payment_attempt(claim_b, foreign_interest["id"], 12000000)
    validate_error(both_violated, "ERR_PAYEE_NOT_ON_POLICY", expected_status=422)


def test_repairing_the_payee_exposes_the_fiscal_ceiling_and_the_exact_ceiling_pays():
    """With the payee corrected the money rule becomes visible: the amount must
    not exceed the target coverage part's available_cents, so 12000000 against a
    part with 10000000 left is refused with ERR_PAYMENT_EXCEEDS_RESERVE while a
    payment at exactly the ceiling is issued. Neither rejected call created a
    payment row.

    Design: Difficulty/priority_pair_validation_conflict/payee_referential_check_outranks_reserve_ceiling_and_rejects_payment
    """
    account, claim_b, foreign_interest = _account_with_stale_allocation()
    owner_interest = account.owner_interest

    _payment_attempt(claim_b, foreign_interest["id"], 12000000)
    over_ceiling = _payment_attempt(claim_b, owner_interest["id"], 12000000)
    validate_error(over_ceiling, "ERR_PAYMENT_EXCEEDS_RESERVE", expected_status=422)

    at_ceiling = _payment_attempt(claim_b, owner_interest["id"], 10000000)
    payment = get_success_data(at_ceiling, expected_status=201)
    assert_loss_payment(payment, status="ISSUED")
    assert payment["amount_cents"] == 10000000, payment["amount_cents"]

    part = account.refresh_parts()["IN_TRANSIT"]
    assert part["eroded_cents"] == 20000000, part["eroded_cents"]
    assert part["available_cents"] == 0, part["available_cents"]

    settled_claim = get_success_data(api_client.get_claim(claim_b["id"], fx.CA))
    assert settled_claim["paid_cents"] == 10000000, settled_claim["paid_cents"]
    assert settled_claim["outstanding_reserve_cents"] == 5000000, settled_claim
    assert settled_claim["payment_status"] == "PARTIALLY_PAID", settled_claim

    rows, _meta = validate_paginated(api_client.list_loss_payments(
        fx.CA, params={"claim_id": claim_b["id"], "limit": 100}))
    assert len(rows) == 1, f"the rejected calls must not persist anything: {rows}"


def _two_endorsements():
    """E1 is already approved and priced above the underwriter's authority; E2 is
    still open and priced below it."""
    account = fx.in_force_account()
    assert account.policy["quoted_premium_cents"] == 2750440, account.policy

    first = fx.file_endorsement(account, 76, slip_reason="LABOR_SHORTAGE")
    first = fx.decide_endorsement(account, first, "APPROVE", headers=fx.UM)
    assert first["additional_premium_cents"] == 968985, first
    assert account.policy["cumulative_extension_days"] == 76, account.policy

    second = fx.file_endorsement(account, 30, slip_reason="WEATHER")
    assert second["additional_premium_cents"] == 382494, second
    return account, first, second


def test_the_authority_gate_outranks_the_endorsement_state_rule():
    """Deciding an already-APPROVED endorsement breaks the state rule, and doing
    it as an Underwriter when the frozen additional premium exceeds the
    single-order authority limit breaks the authority rule. The PRD orders the
    authority check ahead of the state check, so the caller gets
    ERR_MANAGER_APPROVAL_REQUIRED, and a manager attempting the same call then
    sees the state refusal underneath it.

    Design: Difficulty/priority_pair_validation_conflict/manager_approval_gate_outranks_endorsement_state_and_rejects_decision
    """
    _account, first, _second = _two_endorsements()

    both_violated = api_client.decide_endorsement(
        first["id"], {"decision": "APPROVE"}, fx.UW2)
    validate_error(both_violated, "ERR_MANAGER_APPROVAL_REQUIRED",
                   expected_status=403)

    state_only = api_client.decide_endorsement(
        first["id"], {"decision": "APPROVE"}, fx.UM2)
    validate_error(state_only, "ERR_INVALID_ENDORSEMENT_STATE", expected_status=409)


def test_an_underwriter_may_decide_the_endorsement_inside_the_authority_limit():
    """The gate is a threshold on the endorsement's own frozen additional
    premium, not a blanket role rule: E2's 382494 sits at or below the limit, so
    a second underwriter approves it and the policy absorbs both extensions in
    the term end, the adjusted completion date and the written premium.

    Design: Difficulty/priority_pair_validation_conflict/manager_approval_gate_outranks_endorsement_state_and_rejects_decision
    """
    account, _first, second = _two_endorsements()

    approved = get_success_data(api_client.decide_endorsement(
        second["id"], {"decision": "APPROVE"}, fx.UW2))
    assert approved["status"] == "APPROVED", approved
    assert approved["decided_by_user_id"] == fx.UW2["X-User-ID"], approved

    policy = account.refresh_policy()
    assert policy["cumulative_extension_days"] == 106, policy
    assert policy["term_end_date"].startswith("2027-10-14"), policy
    assert policy["adjusted_completion_date"].startswith("2027-09-15"), policy
    assert policy["written_premium_cents"] == 4101919, policy
