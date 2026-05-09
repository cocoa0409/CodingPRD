"""Disbursement: payout creation, bank settle, bank fail, and subrogation.

Pinned to PRD §3.6 (payout flow, subrogation, invariants), §2.9 (negative-net guard).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_subrogation_payload,
    setup_claim_approved, setup_claim_paid, setup_claim_settled,
    create_payout, post_subrogation, bank_settle, bank_fail, get_claim,
    make_payout_officer_headers, TEST_USERS,
    assert_payout, assert_payout_balance_invariant,
    assert_exactly_one_succeeds, run_race, validate_error_is_one_of,
)


# ─── §3.6 payout creation ────────────────────────────────────────
def test_create_payout_for_approved_claim(api):
    """PRD §3.6: "Once a claim reaches `APPROVED` and its `net_payout_cents`
    is strictly greater than zero, a `PayoutOfficer` may create a payout
    against the claim. Creation establishes a single `Payout` row in
    `PENDING` status whose `claim_id` references the parent claim and
    whose `amount_cents` is a snapshot of the claim's current
    `net_payout_cents`. ... Creation also moves the claim from `APPROVED`
    to `PAID` and records the audit log event."

    Claim: POST /payouts on an APPROVED claim -> Payout PENDING with
    amount_cents == Claim.net_payout_cents; Claim transitions to PAID.
    """
    state = setup_claim_approved(
        assessed_loss_cents=500_000,
        deductible_cents=100_000,
        coinsurance_ratio=0.8000,
        coverage_limit_cents=1_000_000,
        salvage_value_cents=50_000,
        claimed_amount_cents=5_000_000,  # MANUAL path
    )
    state = create_payout(state)
    payout = state["payout"]
    assert_payout(payout)
    assert payout["status"] == "PENDING"
    assert payout["claim_id"] == state["claim"]["id"]
    # net = gross(320000) - salvage(50000) = 270000
    assert state["claim"]["net_payout_cents"] == 270_000
    assert payout["amount_cents"] == 270_000
    # Claim transitioned APPROVED -> PAID
    refreshed = get_claim(state["claim"]["id"])
    assert refreshed["status"] == "PAID"


def test_double_payout_creation_rejected(api):
    """PRD §3.6: "Two simultaneous payout-creation requests for the same
    claim serialise on the per-claim uniqueness constraint; the loser is
    rejected with `ERR_PAYOUT_ALREADY_EXISTS`."

    Claim: a second POST /payouts after the first has succeeded -> rejected.
    Per PRD §2.6 priority cascade, the state check (Claim no longer APPROVED
    after first succeeds) takes priority; therefore the rejection MAY be
    ERR_INVALID_STATE OR ERR_PAYOUT_ALREADY_EXISTS — we accept either with
    validate_error_is_one_of.

    # difficulty: cross_entity_state_dependency/payout_creation_requires_no_existing_payout_and_approved_claim
    """
    state = setup_claim_paid(
        salvage_value_cents=50_000,
    )
    # First payout already created in setup_claim_paid; try again sequentially.
    res = api.create_payout(state["claim"]["id"], TEST_USERS["payout_officer_headers"])
    err_id = validate_error_is_one_of(res, ["ERR_INVALID_STATE", "ERR_PAYOUT_ALREADY_EXISTS"])
    assert err_id in ("ERR_INVALID_STATE", "ERR_PAYOUT_ALREADY_EXISTS")


def test_payout_rbac_only_payout_officer(api, customer_headers):
    """PRD §4 endpoints table: POST /claims/{id}/payouts is PayoutOfficer-only.

    Claim: Customer calling payouts -> ERR_FORBIDDEN.
    """
    state = setup_claim_approved(
        claimed_amount_cents=5_000_000, assessed_loss_cents=500_000,
        coverage_limit_cents=10_000_000,
    )
    res = api.create_payout(state["claim"]["id"], customer_headers)
    validate_error(res, "ERR_FORBIDDEN")


# ─── §3.6 bank settle / fail ─────────────────────────────────────
def test_bank_settle_cascades_payout_settled_and_claim_closed(api):
    """PRD §3.6: "Bank settlement transitions the payout from `PENDING`
    to `SETTLED`, stamps the payout's `settled_at` and a server-generated
    `bank_reference`, and cascades the claim from `PAID` to `CLOSED`."

    Claim: bank-settle event -> Payout SETTLED with bank_reference; Claim CLOSED.

    # difficulty: transitive_cascade/bank_settle_to_policy_event_sync_depth3
    # difficulty: non_linear_state_machine/payout_branching_with_compensation
    """
    state = setup_claim_paid(salvage_value_cents=50_000)
    bank_settle(state["payout"]["id"])
    # Refetch payout & claim.
    payout = validate_success(api.get_payout(state["claim"]["id"], TEST_USERS["admin_headers"]))
    assert payout["status"] == "SETTLED"
    assert payout["bank_reference"], "bank_reference must be set after settle"
    assert payout["settled_at"], "settled_at must be set after settle"
    refreshed = get_claim(state["claim"]["id"])
    assert refreshed["status"] == "CLOSED"


def test_bank_fail_reverses_payout_and_reverts_claim(api):
    """PRD §3.6: "When the bank-fail event fires on a `PENDING` payout,
    the payout transitions to `REVERSED` and the claim reverts from `PAID`
    back to `APPROVED` so that a new payout attempt can be made; the
    claim's `gross_payout_cents` and `net_payout_cents` are deliberately
    left unchanged because only the payout row reverses."

    Claim: bank-fail -> Payout REVERSED, Claim APPROVED, monetary fields unchanged.

    # difficulty: non_linear_state_machine/payout_branching_with_compensation
    # difficulty: compensating_invariant/bank_fail_revert_preserves_payout_count_invariant
    """
    state = setup_claim_paid(salvage_value_cents=50_000)
    pre_gross = state["claim"]["gross_payout_cents"]
    pre_net = state["claim"]["net_payout_cents"]
    bank_fail(state["payout"]["id"])
    refreshed = get_claim(state["claim"]["id"])
    assert refreshed["status"] == "APPROVED"
    assert refreshed["gross_payout_cents"] == pre_gross
    assert refreshed["net_payout_cents"] == pre_net


def test_bank_fail_then_retry_payout_succeeds(api):
    """PRD §3.6: "A bank-fail event followed by another payout creation for
    the same claim is allowed (the first payout is in `REVERSED` and no
    longer counts toward the per-claim uniqueness constraint)."

    Claim: after bank-fail, a second POST /payouts succeeds and creates a
    distinct PENDING Payout row.

    # difficulty: compensating_invariant/bank_fail_revert_preserves_payout_count_invariant
    """
    state = setup_claim_paid(salvage_value_cents=50_000)
    p1_id = state["payout"]["id"]
    bank_fail(p1_id)
    # Retry.
    res = api.create_payout(state["claim"]["id"], TEST_USERS["payout_officer_headers"])
    p2 = validate_success(res, expected_status=201)
    assert p2["status"] == "PENDING"
    assert p2["id"] != p1_id


# ─── §3.6 subrogation ─────────────────────────────────────────────
def test_subrogation_increments_recovery_and_recomputes_net_only(api):
    """PRD §3.6: "After a payout has settled, third-party recoveries may
    continue to arrive. The `PayoutOfficer` records each recovery with a
    positive `amount_cents`; the server adds it to
    `Claim.subrogation_recovery_cents`, recomputes `Claim.net_payout_cents`
    in its `post_recovery` variant (gross stays fixed; net drops by the
    new recovery), and writes an audit `PAYOUT_EVENT`. The original
    `Payout.amount_cents` is not retroactively altered — recoveries are
    bookkeeping entries, not payment reversals."

    Claim: subrogation amount=30000 -> subrogation_recovery_cents=30000,
    net drops by 30000, gross unchanged, original Payout.amount_cents unchanged.

    # difficulty: combinatorial_formula/net_payout_circular_evaluation_order
    # difficulty: compensating_invariant/subrogation_preserves_gross_minus_recoveries_equals_net
    """
    # Use setup_claim_paid (Claim PAID, payout PENDING) — PRD §3.6 gates
    # subrogation on Claim.status == PAID. We do not bank-settle first
    # because the bank-settle cascade transitions Claim PAID -> CLOSED.
    state = setup_claim_paid(
        assessed_loss_cents=500_000,
        deductible_cents=100_000,
        coinsurance_ratio=0.8000,
        salvage_value_cents=50_000,
    )
    pre_gross = state["claim"]["gross_payout_cents"]  # 320000
    pre_net = state["claim"]["net_payout_cents"]      # 270000
    pre_payout_amount = state["payout"]["amount_cents"]
    state = post_subrogation(state, amount_cents=30_000)
    refreshed = get_claim(state["claim"]["id"])
    assert refreshed["gross_payout_cents"] == pre_gross == 320_000
    assert refreshed["subrogation_recovery_cents"] == 30_000
    assert refreshed["net_payout_cents"] == pre_net - 30_000 == 240_000
    # Payout row's recorded amount unchanged.
    payout = validate_success(api.get_payout(state["claim"]["id"], TEST_USERS["admin_headers"]))
    assert payout["amount_cents"] == pre_payout_amount


def test_subrogation_invariant_holds_across_two_steps(api):
    """PRD §3.5 (Net payout): "The compensating invariant — that
    `gross_payout_cents` minus `salvage_value_cents` minus
    `subrogation_recovery_cents` equals `net_payout_cents` — must hold
    at all times."

    Claim: after two sequential subrogations, gross unchanged and the
    invariant gross - salvage - subrog == net holds.

    # difficulty: compensating_invariant/subrogation_preserves_gross_minus_recoveries_equals_net
    """
    # Claim PAID (payout PENDING) — PRD §3.6 gates subrogation on PAID.
    state = setup_claim_paid(
        assessed_loss_cents=500_000,
        deductible_cents=100_000,
        coinsurance_ratio=0.8000,
        salvage_value_cents=50_000,
    )
    # Step 1: subrog 30000.
    state = post_subrogation(state, amount_cents=30_000)
    refreshed = get_claim(state["claim"]["id"])
    assert refreshed["gross_payout_cents"] == 320_000
    assert refreshed["salvage_value_cents"] == 50_000
    assert refreshed["subrogation_recovery_cents"] == 30_000
    assert refreshed["net_payout_cents"] == 240_000
    assert_payout_balance_invariant(refreshed)
    # Step 2: subrog 10000.
    state = post_subrogation(state, amount_cents=10_000)
    refreshed = get_claim(state["claim"]["id"])
    assert refreshed["gross_payout_cents"] == 320_000  # still pinned
    assert refreshed["subrogation_recovery_cents"] == 40_000
    assert refreshed["net_payout_cents"] == 230_000
    assert_payout_balance_invariant(refreshed)


def test_subrogation_negative_net_payout_rejected(api):
    """PRD §3.6: "A recovery that, taken together with `salvage_value_cents`,
    would push their combined sum above `gross_payout_cents` (and therefore
    push net below zero) is rejected with `ERR_NEGATIVE_NET_PAYOUT`."

    Claim: subrogation that would push (salvage + subrog) > gross ->
    ERR_NEGATIVE_NET_PAYOUT.
    """
    # Subrogation requires payout SETTLED per PRD §3.6 — use settled fixture.
    state = setup_claim_settled(
        assessed_loss_cents=500_000,
        deductible_cents=100_000,
        coinsurance_ratio=0.8000,
        salvage_value_cents=50_000,  # gross=320000, net=270000
    )
    # Subrog 290000 would push salvage+subrog = 50000+290000 = 340000 > 320000.
    res = api.create_subrogation(
        state["claim"]["id"],
        create_subrogation_payload(amount_cents=290_000),
        TEST_USERS["payout_officer_headers"],
    )
    validate_error(res, "ERR_NEGATIVE_NET_PAYOUT")


def test_subrogation_requires_paid_claim(api):
    """PRD §3.6: "Recording a recovery requires the claim to be in `PAID`
    status with the underlying payout in `SETTLED`; if a bank-fail event
    has just flipped the claim back to `APPROVED`, a racing subrogation
    post is rejected with `ERR_INVALID_STATE`."

    Claim: subrogation on an APPROVED claim (after bank-fail) -> ERR_INVALID_STATE.
    """
    state = setup_claim_paid(salvage_value_cents=50_000)
    bank_fail(state["payout"]["id"])  # claim back to APPROVED
    res = api.create_subrogation(
        state["claim"]["id"],
        create_subrogation_payload(amount_cents=10_000),
        TEST_USERS["payout_officer_headers"],
    )
    validate_error(res, "ERR_INVALID_STATE")


def test_subrogation_rbac_only_payout_officer(api, customer_headers):
    """PRD §4 endpoints table: POST /claims/{id}/subrogations is PayoutOfficer-only.

    Claim: Customer calling subrogations -> ERR_FORBIDDEN.
    """
    state = setup_claim_paid(salvage_value_cents=50_000)
    res = api.create_subrogation(
        state["claim"]["id"],
        create_subrogation_payload(amount_cents=10_000),
        customer_headers,
    )
    validate_error(res, "ERR_FORBIDDEN")
