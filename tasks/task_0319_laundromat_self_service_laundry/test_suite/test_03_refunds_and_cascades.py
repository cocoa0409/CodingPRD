"""Refund-claim adjudication, cascade settlement, and conservation invariants."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
    setup_app_wallet_vend,
    setup_submitted_wallet_claim,
    setup_refunded_vend,
    file_refund_claim,
    approve_refund_claim,
    get_member,
    get_vend,
    create_plan,
    set_clock,
)

MANAGER = TEST_USERS["manager_headers"]
ATTENDANT = TEST_USERS["attendant_headers"]


def _latest_ledger(api, member_id):
    data = validate_success(api.list_member_loyalty_ledger(member_id, MANAGER), 200)
    return data


def test_refund_approve_cascade_depth3(api):
    """PRD §3.7: "the vend's `payment_status` moves `CAPTURED → REFUNDED`. The
    cascade then settles the money and the points: if the vend was paid by
    `APP_WALLET` and the refund destination is `WALLET`, the member's
    `wallet_cents` is credited the approved amount; a `REVERSAL` loyalty ledger
    entry of negative the vend's `loyalty_points_earned` is written and the
    member's `loyalty_points` is reduced by that many points, floored at zero;
    the member's `lifetime_spend_cents` is reduced by the vend's
    `charged_amount_cents`, floored at zero".

    Design: Difficulty/transitive_cascade/refund_approve_cascade_depth3_vend_member_ledger
    """
    # wash_base 300, loyalty_cents_per_point 100 -> vend accrues 3 points.
    plan, machine, member, vend, claim = setup_submitted_wallet_claim(
        reason="NO_CYCLE", principal_cents=5000,
        plan_overrides={"loyalty_cents_per_point": 100})
    # Pre-approval: wallet 5500-300=5200, points 3, lifetime 300.
    pre = get_member(member["id"])
    assert pre["wallet_cents"] == 5200 and pre["loyalty_points"] == 3
    approve_refund_claim(claim["id"], claim["version"])
    assert get_vend(vend["id"])["payment_status"] == "REFUNDED"
    post = get_member(member["id"])
    assert post["wallet_cents"] == 5500, "wallet credited back the 300"
    assert post["loyalty_points"] == 0, "3 points reversed"
    assert post["lifetime_spend_cents"] == 0, "lifetime spend reduced by charged amount"
    ledger = _latest_ledger(api, member["id"])
    last = ledger[-1]
    assert last["entry_type"] == "REVERSAL"
    assert last["points_delta"] == -3


def test_refund_preserves_wallet_conservation(api):
    """PRD §3.7: "if the vend was paid by `APP_WALLET` and the refund destination
    is `WALLET`, the member's `wallet_cents` is credited the approved amount".
    PRD §3.7: "On approval `approved_cents` equals `requested_cents` exactly —
    refunds are full, never partial."

    Design: Difficulty/compensating_invariant/refund_preserves_wallet_money_conservation
    """
    plan, machine, member, vend, claim = setup_submitted_wallet_claim(
        reason="NO_CYCLE", principal_cents=5000,
        plan_overrides={"loyalty_cents_per_point": 100})
    approve_refund_claim(claim["id"], claim["version"])
    # 5500 credited - 300 charged + 300 refunded == 5500.
    assert get_member(member["id"])["wallet_cents"] == 5500
    assert get_vend(vend["id"])["payment_status"] == "REFUNDED"


def test_loyalty_accrual_reversal_conservation(api):
    """PRD §3.4: "Every movement of points — accrual on a vend, reversal on a
    refund, or redemption — is recorded as an immutable `LoyaltyLedgerEntry`".
    PRD §3.7: "a `REVERSAL` loyalty ledger entry of negative the vend's
    `loyalty_points_earned` is written and the member's `loyalty_points` is
    reduced by that many points, floored at zero".

    Design: Difficulty/compensating_invariant/loyalty_accrual_reversal_preserves_points_conservation
    """
    plan, machine, member, vend, claim = setup_submitted_wallet_claim(
        reason="NO_CYCLE", principal_cents=5000,
        plan_overrides={"loyalty_cents_per_point": 100})
    approve_refund_claim(claim["id"], claim["version"])
    assert get_member(member["id"])["loyalty_points"] == 0
    ledger = _latest_ledger(api, member["id"])
    accrual_reversal = [e for e in ledger if e["entry_type"] in ("ACCRUAL", "REVERSAL")]
    assert sum(e["points_delta"] for e in accrual_reversal) == 0, "+3 accrual, -3 reversal sum to 0"


def test_lifetime_spend_reconciled_after_refund(api):
    """PRD §3.7: "the member's `lifetime_spend_cents` is reduced by the vend's
    `charged_amount_cents`, floored at zero".

    Design: Corner/cross_cutting_complexity_layers/derived_lifetime_spend_reconciled_after_refund
    """
    plan, machine, member, vend, claim = setup_submitted_wallet_claim(
        reason="NO_CYCLE", principal_cents=5000,
        plan_overrides={"loyalty_cents_per_point": 100})
    assert get_member(member["id"])["lifetime_spend_cents"] == 300
    approve_refund_claim(claim["id"], claim["version"])
    assert get_member(member["id"])["lifetime_spend_cents"] == 0


def test_deny_refund_leaves_vend_captured(api):
    """PRD §3.7: "Denying a `SUBMITTED` claim moves it `SUBMITTED → DENIED`,
    leaves `approved_cents` at zero, and changes nothing about the vend."

    Design: Corner/endpoints/deny_refund_leaves_vend_captured
    """
    plan, machine, member, vend = setup_app_wallet_vend(
        principal_cents=5000, plan_overrides={"loyalty_cents_per_point": 100})
    claim = file_refund_claim(vend["id"], member["id"], reason="DOUBLE_CHARGE",
                              refund_destination="WALLET", as_member_id=member["id"])
    resp = api.deny_refund_claim(claim["id"], MANAGER)
    denied = validate_success(resp, 200)
    assert denied["status"] == "DENIED"
    assert denied["approved_cents"] == 0
    assert get_vend(vend["id"])["payment_status"] == "CAPTURED"
    assert get_member(member["id"])["wallet_cents"] == 5200, "wallet unchanged after deny"


def test_approve_already_refunded_vend_rejected(api):
    """PRD §3.7: "Approving a `SUBMITTED` claim ... requires ... the referenced
    vend's `payment_status` to still be `CAPTURED` and not already `REFUNDED`
    (else `ERR_ALREADY_REFUNDED`)".

    Design: Difficulty/cross_entity_state_dependency/refund_approve_requires_vend_captured
    """
    plan, machine, member, vend, claim1 = setup_refunded_vend(
        reason="MACHINE_FAULT", principal_cents=5000,
        plan_overrides={"loyalty_cents_per_point": 100})
    assert get_vend(vend["id"])["payment_status"] == "REFUNDED"
    # A second claim against the already-refunded vend cannot be approved.
    claim2 = file_refund_claim(vend["id"], member["id"], reason="DOUBLE_CHARGE",
                               refund_destination="WALLET", as_member_id=member["id"])
    resp = api.approve_refund_claim(
        claim2["id"], {"expected_claim_version": claim2["version"]}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_ALREADY_REFUNDED.value)
    assert get_vend(vend["id"])["payment_status"] == "REFUNDED"


def test_approve_already_approved_claim_rejected(api):
    """PRD §3.7: "Approval requires the claim to be `SUBMITTED`".
    PRD §2.10: "State validity is sixth: the target resource must be in a state
    that admits the requested transition, or `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/refund_approve_twice_idempotency_rejected
    """
    plan, machine, member, vend, claim = setup_submitted_wallet_claim(
        reason="NO_CYCLE", principal_cents=5000,
        plan_overrides={"loyalty_cents_per_point": 100})
    approved = approve_refund_claim(claim["id"], claim["version"])
    assert approved["status"] == "APPROVED"
    # Approving again with the post-approval version: the claim is terminal.
    resp = api.approve_refund_claim(
        claim["id"], {"expected_claim_version": approved["version"]}, MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_vend(vend["id"])["payment_status"] == "REFUNDED"
