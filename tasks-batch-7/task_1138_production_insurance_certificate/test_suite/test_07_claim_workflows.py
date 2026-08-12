"""Claim workflows: deductible math, reserve adjust cycle, settlement and
denial side effects, segregation of duties, and error cases (PRD §2.9, §3.8)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    build_user_headers, NON_EXISTENT_UUID,
    set_logical_clock, create_production,
    setup_active_production_with_bound_policy, setup_claim_under_review,
    report_claim, list_claim_event_types,
    assert_claim_amount_invariant,
    TEST_USERS,
)

BROKER = TEST_USERS["broker_headers"]
PM = TEST_USERS["production_manager_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]


# ─── Deductible exact boundary (difficulty) ───────────

def test_claim_deductible_exact_boundary(api):
    """PRD §3.8: "The boundary case is exact: when the loss amount equals the
    per-claim deductible, the deductible applied equals the whole loss and the
    carrier pays nothing — the claim sits entirely on the production."

    Design: Difficulty/boundary_precision_check/claim_deductible_exact_boundary
    """
    prod, policy = setup_active_production_with_bound_policy(
        policy_overrides={"deductible_cents": 250000})
    claim = report_claim(prod["id"], policy["id"], loss_amount_cents=250000)
    assert claim["deductible_applied_cents"] == 250000
    assert claim["carrier_payable_cents"] == 0
    assert_claim_amount_invariant(claim)


@pytest.mark.parametrize("loss,expected_ded,expected_pay", [
    (249999, 249999, 0),   # one cent below the deductible
    (250001, 250000, 1),   # one cent above the deductible
])
def test_claim_deductible_boundary_neighbors(api, loss, expected_ded, expected_pay):
    """PRD §3.8: "The **deductible applied** is the smallest of three figures:
    the policy's per-claim `deductible_cents`, the claim's own
    `loss_amount_cents`, and the room remaining under the policy's annual
    aggregate deductible cap."
    PRD §3.8: "the carrier's share, `carrier_payable_cents`, is the loss amount
    minus the deductible applied."

    Design: Difficulty/boundary_precision_check/claim_deductible_exact_boundary
    """
    prod, policy = setup_active_production_with_bound_policy(
        policy_overrides={"deductible_cents": 250000})
    claim = report_claim(prod["id"], policy["id"], loss_amount_cents=loss)
    assert claim["deductible_applied_cents"] == expected_ded
    assert claim["carrier_payable_cents"] == expected_pay
    assert_claim_amount_invariant(claim)


# ─── Deductible below-deductible case (corner) ────────

def test_claim_deductible_applied_cents_below_deductible(api):
    """PRD §3.8: "The **deductible applied** is the smallest of three figures:
    the policy's per-claim `deductible_cents`, the claim's own
    `loss_amount_cents`, and the room remaining under the policy's annual
    aggregate deductible cap."

    Loss 150000 against deductible 200000 -> the loss itself is the smallest
    figure, so the carrier pays nothing.

    Design: Corner/calculations/claim_deductible_applied_cents_below_deductible
    """
    prod, policy = setup_active_production_with_bound_policy(
        policy_overrides={"deductible_cents": 200000})
    claim = report_claim(prod["id"], policy["id"], loss_amount_cents=150000)
    assert claim["deductible_applied_cents"] == 150000
    assert claim["carrier_payable_cents"] == 0
    assert_claim_amount_invariant(claim)


# ─── Adjust cycle (difficulty) ────────────────────────

def test_claim_under_review_adjust_cycle(api):
    """PRD §3.8: "adjusting the reserve with a `new_reserve_cents` value of
    zero or more moves the claim `UNDER_REVIEW` → `ADJUSTED`, and a further
    adjustment moves it `ADJUSTED` → `UNDER_REVIEW` again; the cycle may repeat
    as often as the adjuster needs, each pass overwriting `reserve_cents`."

    Design: Difficulty/non_linear_state_machine/claim_under_review_adjust_cycle
    """
    prod, policy, claim = setup_claim_under_review(loss_amount_cents=5000000)
    assert claim["status"] == "UNDER_REVIEW"

    step1 = validate_success(
        api.adjust_claim(prod["id"], claim["id"], {"new_reserve_cents": 3000000}, ADJ),
        200)
    assert step1["status"] == "ADJUSTED"
    step2 = validate_success(
        api.adjust_claim(prod["id"], claim["id"], {"new_reserve_cents": 4500000}, ADJ),
        200)
    assert step2["status"] == "UNDER_REVIEW"
    assert step2["reserve_cents"] == 4500000
    step3 = validate_success(
        api.adjust_claim(prod["id"], claim["id"], {"new_reserve_cents": 2000000}, ADJ),
        200)
    assert step3["status"] == "ADJUSTED"
    assert step3["reserve_cents"] == 2000000


def test_claim_adjust_cycle_appends_adjust_reserve_events(api):
    """PRD §3.8: "Acknowledgement emits `SUBMIT`; each reserve adjustment emits
    `ADJUST_RESERVE`; denial emits `DENY`; settlement emits `SETTLE`; closing
    emits `CLOSE`."
    PRD §3.8: "The event log is readable per claim"

    Design: Difficulty/non_linear_state_machine/claim_under_review_adjust_cycle
    """
    prod, policy, claim = setup_claim_under_review(loss_amount_cents=5000000)
    for reserve in (3000000, 4500000, 2000000):
        validate_success(
            api.adjust_claim(prod["id"], claim["id"],
                             {"new_reserve_cents": reserve}, ADJ),
            200)
    events = list_claim_event_types(prod["id"], claim["id"])
    assert events.count("ADJUST_RESERVE") >= 3
    assert "SUBMIT" in events


# ─── Reserve conservation (difficulty) ────────────────

def test_claim_reserve_conservation_across_settle(api):
    """PRD §3.8: "Settlement zeroes the reserve and lands the claim in
    `SETTLED`, from either `UNDER_REVIEW` or `ADJUSTED`."
    PRD §3.8: "the carrier's share, `carrier_payable_cents`, is the loss amount
    minus the deductible applied."

    Settling compensates the reserved exposure back to zero while the claim's
    loss/deductible/payable figures are untouched:
    loss == deductible_applied + carrier_payable holds at every state.

    Design: Difficulty/compensating_invariant/claim_reserve_conservation
    """
    prod, policy, claim = setup_claim_under_review(
        loss_amount_cents=500000, deductible_cents=100000)
    assert claim["deductible_applied_cents"] == 100000
    assert claim["carrier_payable_cents"] == 400000
    assert claim["reserve_cents"] == 400000

    settled = validate_success(
        api.settle_claim(prod["id"], claim["id"],
                         {"settlement_amount_cents": 300000}, ADJ), 200)
    assert settled["status"] == "SETTLED"

    after = validate_success(api.get_claim(prod["id"], claim["id"], ADJ), 200)
    assert after["loss_amount_cents"] == 500000
    assert after["deductible_applied_cents"] == 100000
    assert after["carrier_payable_cents"] == 400000
    assert after["reserve_cents"] == 0
    assert_claim_amount_invariant(after)


def test_claim_reserve_conservation_across_deny(api):
    """PRD §3.8: "Denial from `UNDER_REVIEW` requires a non-empty `reason`;
    denial from `ADJUSTED` carries no precondition at all — either way the
    reserve is zeroed."
    PRD §3.8: "the carrier's share, `carrier_payable_cents`, is the loss amount
    minus the deductible applied."

    Denial is the other compensating path: reserve returns to zero while the
    loss/deductible/payable decomposition is conserved.

    Design: Difficulty/compensating_invariant/claim_reserve_conservation
    """
    prod, policy, claim = setup_claim_under_review(
        loss_amount_cents=500000, deductible_cents=100000)
    denied = validate_success(
        api.deny_claim(prod["id"], claim["id"], {"reason": "Not covered"}, ADJ), 200)
    assert denied["status"] == "DENIED"

    after = validate_success(api.get_claim(prod["id"], claim["id"], ADJ), 200)
    assert after["loss_amount_cents"] == 500000
    assert after["deductible_applied_cents"] == 100000
    assert after["carrier_payable_cents"] == 400000
    assert after["reserve_cents"] == 0
    assert_claim_amount_invariant(after)


# ─── Settle side effects (corner) ─────────────────────

def test_claim_side_effects_on_settle(api):
    """PRD §3.8: "Settlement zeroes the reserve and lands the claim in
    `SETTLED`, from either `UNDER_REVIEW` or `ADJUSTED`."
    PRD §3.8: "Acknowledgement emits `SUBMIT`; each reserve adjustment emits
    `ADJUST_RESERVE`; denial emits `DENY`; settlement emits `SETTLE`; closing
    emits `CLOSE`."

    Design: Corner/state_machines/claim_side_effects_on_settle
    """
    prod, policy, claim = setup_claim_under_review(
        loss_amount_cents=500000, deductible_cents=100000)
    settled = validate_success(
        api.settle_claim(prod["id"], claim["id"],
                         {"settlement_amount_cents": 300000}, ADJ), 200)
    assert settled["status"] == "SETTLED"
    assert settled["reserve_cents"] == 0
    events = list_claim_event_types(prod["id"], claim["id"])
    assert "SUBMIT" in events
    assert "SETTLE" in events


# ─── Settlement exceeds reserve (corner) ──────────────

def test_settlement_exceeds_reserve_returns_fiscal_error(api):
    """PRD §3.8: "Settlement takes a `settlement_amount_cents` that must be
    zero or more and must not exceed the claim's current `reserve_cents` — an
    overage is rejected with `ERR_SETTLEMENT_EXCEEDS_RESERVE`"

    Design: Corner/validations/settlement_exceeds_reserve_returns_fiscal_error
    """
    prod, policy, claim = setup_claim_under_review(
        loss_amount_cents=500000, deductible_cents=100000)
    res = api.settle_claim(prod["id"], claim["id"],
                           {"settlement_amount_cents": 999999}, ADJ)
    validate_error(res, "ERR_SETTLEMENT_EXCEEDS_RESERVE", expected_status=422)


# ─── Segregation of duties vs fiscal (difficulty) ─────

def test_self_settlement_with_over_reserve_returns_self_settlement_error(api):
    """PRD §2.9: "Inbound requests are validated in a fixed order, and the
    first failure wins — a response never reports more than one error, and an
    earlier failure masks everything after it."
    PRD §2.9 step 7: "Segregation of duties on claim settlement: the request is
    refused with `ERR_SELF_SETTLEMENT_FORBIDDEN` (403) when the adjuster's
    `X-User-ID` equals the identifier that originally submitted the claim."

    The settling operator carries the same X-User-ID as the submitter AND the
    amount exceeds the reserve; the segregation check (step 7) precedes the
    fiscal check (step 17), so ERR_SELF_SETTLEMENT_FORBIDDEN wins.

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_claim_settle
    """
    submitter = build_user_headers("pm-user-001", "ProductionManager")
    same_id_adjuster = build_user_headers("pm-user-001", "ClaimsAdjuster")
    prod, policy, claim = setup_claim_under_review(
        loss_amount_cents=500000, deductible_cents=100000,
        submitter_headers=submitter)
    res = api.settle_claim(prod["id"], claim["id"],
                           {"settlement_amount_cents": 999999999},
                           same_id_adjuster)
    validate_error(res, "ERR_SELF_SETTLEMENT_FORBIDDEN", expected_status=403)


def test_self_settlement_with_valid_amount_still_forbidden(api):
    """PRD §3.8: "it enforces segregation of duties: the same `X-User-ID` that
    submitted the claim may not settle it, and a matching pair is refused with
    `ERR_SELF_SETTLEMENT_FORBIDDEN` (HTTP 403)."

    Isolation companion: the amount is within reserve, so segregation of
    duties is the only rule that can fire.

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_fiscal_on_claim_settle
    """
    submitter = build_user_headers("pm-user-002", "ProductionManager")
    same_id_adjuster = build_user_headers("pm-user-002", "ClaimsAdjuster")
    prod, policy, claim = setup_claim_under_review(
        loss_amount_cents=500000, deductible_cents=100000,
        submitter_headers=submitter)
    res = api.settle_claim(prod["id"], claim["id"],
                           {"settlement_amount_cents": 300000},
                           same_id_adjuster)
    validate_error(res, "ERR_SELF_SETTLEMENT_FORBIDDEN", expected_status=403)


# ─── Claim action on nonexistent claim (corner) ───────

def test_claim_action_on_nonexistent_claim_returns_404(api):
    """PRD §2.9: "Any identifier that does not resolve to an existing entity
    is `ERR_NOT_FOUND` (404)."

    Design: Corner/endpoints/claim_action_on_nonexistent_claim_returns_404
    """
    set_logical_clock()
    prod = create_production()
    res = api.acknowledge_claim(prod["id"], NON_EXISTENT_UUID, ADJ)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)
