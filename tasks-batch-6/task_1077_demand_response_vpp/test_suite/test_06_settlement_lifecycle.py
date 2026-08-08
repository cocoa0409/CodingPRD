"""Settlement approval cascade, the dispute/revise/resubmit cycle, payment
reversal compensation, segregation of duties, OCC, and mark-paid clearing.

Queue A: settlement_pending_dispute_revise_resubmit_cycle,
settlement_approve_payout_cascade, aggregator_paid_balance_conserved_on_dispute.
Queue B: approve_same_user_sod_forbidden, patch_program_stale_version_rejected,
mark_paid_clears_payments.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    make_aggregator_headers,
    create_program_payload,
    setup_submitted_settlement, setup_approved_settlement,
)
from test_helpers.api_client import api_client

OP = TEST_USERS["program_operator_headers"]      # op1 (dispatcher)
OP2 = TEST_USERS["second_operator_headers"]      # op2 (clean approver)


# --------------------------------------------------------------------------- #
# non_linear_state_machine / settlement_pending_dispute_revise_resubmit_cycle
# --------------------------------------------------------------------------- #
def test_settlement_dispute_then_revise(api):
    """PRD §3.7: "An Aggregator that participated in the event — one holding at
    least one dispatch in this settlement's event — may dispute the settlement,
    moving it to DISPUTED and incrementing version by 1".
    PRD §3.7: "A ProgramOperator revises a DISPUTED settlement, moving it to
    REVISED and incrementing version by 1".

    Design: Difficulty/non_linear_state_machine/settlement_pending_dispute_revise_resubmit_cycle
    """
    ctx = setup_submitted_settlement(settlement_method="PAY_FOR_PERFORMANCE", event_load=4.0)
    agg_h = make_aggregator_headers(ctx["agg_id"])
    disputed = validate_success(api.dispute_settlement(ctx["set_id"], agg_h))
    assert disputed["status"] == "DISPUTED"
    revised = validate_success(api.revise_settlement(ctx["set_id"], OP))
    assert revised["status"] == "REVISED"


def test_settlement_resubmit_returns_to_pending_approval(api):
    """PRD §3.7: "A REVISED settlement can be submitted again, returning to
    PENDING_APPROVAL (recomputing its net) and re-entering the approval path —
    this forms the recurring PENDING_APPROVAL → DISPUTED → REVISED →
    PENDING_APPROVAL loop until the parties settle."

    Design: Difficulty/non_linear_state_machine/settlement_pending_dispute_revise_resubmit_cycle
    """
    ctx = setup_submitted_settlement(settlement_method="PAY_FOR_PERFORMANCE", event_load=4.0)
    agg_h = make_aggregator_headers(ctx["agg_id"])
    get_success_data(api.dispute_settlement(ctx["set_id"], agg_h))
    get_success_data(api.revise_settlement(ctx["set_id"], OP))
    resubmitted = validate_success(api.submit_settlement(ctx["set_id"], OP))
    assert resubmitted["status"] == "PENDING_APPROVAL", "cycle must close back to PENDING_APPROVAL"


# --------------------------------------------------------------------------- #
# transitive_cascade / settlement_approve_payout_cascade
# --------------------------------------------------------------------------- #
def test_approve_creates_issued_payment(api):
    """PRD §3.7: "for each distinct aggregator appearing among the event's
    COMPLETED dispatches, the system creates one Payment in ISSUED status whose
    amount_cents is that aggregator's summed dispatch net_payment_cents across the
    eligible dispatches, linked to the originating settlement through
    settlement_id and to the payee through aggregator_id."

    Design: Difficulty/transitive_cascade/settlement_approve_payout_cascade
    """
    ctx = setup_approved_settlement(settlement_method="PAY_FOR_PERFORMANCE", event_load=4.0)
    payments = get_success_data(api.list_settlement_payments(ctx["set_id"], OP))
    assert len(payments) == 1
    pay = payments[0]
    assert pay["status"] == "ISSUED"
    assert pay["amount_cents"] == 500  # hop 1


def test_approve_recomputes_aggregator_paid_balance(api):
    """PRD §3.7: "Second, because each payment was created ISSUED, each affected
    aggregator's paid_balance_cents is recomputed as the sum of its ISSUED and
    CLEARED payment amounts."

    Design: Difficulty/transitive_cascade/settlement_approve_payout_cascade
    """
    ctx = setup_approved_settlement(settlement_method="PAY_FOR_PERFORMANCE", event_load=4.0)
    agg = validate_success(api.get_aggregator(ctx["agg_id"], OP))
    assert agg["paid_balance_cents"] == 500  # hop 2, caused by hop 1


# --------------------------------------------------------------------------- #
# compensating_invariant / aggregator_paid_balance_conserved_on_dispute
# --------------------------------------------------------------------------- #
def test_dispute_after_approval_reverses_payment(api):
    """PRD §3.7: "Disputing an APPROVED settlement additionally compensates the
    already-issued payouts: every payment of this settlement still in ISSUED
    status is moved to REVERSED, and each affected aggregator's paid_balance_cents
    is recomputed with the reversed payments excluded, so the paid-balance ledger
    unwinds exactly what approval added."

    Design: Difficulty/compensating_invariant/aggregator_paid_balance_conserved_on_dispute
    """
    ctx = setup_approved_settlement(settlement_method="PAY_FOR_PERFORMANCE", event_load=4.0)
    before = validate_success(api.get_aggregator(ctx["agg_id"], OP))
    assert before["paid_balance_cents"] == 500
    get_success_data(api.dispute_settlement(ctx["set_id"], make_aggregator_headers(ctx["agg_id"])))
    payments = get_success_data(api.list_settlement_payments(ctx["set_id"], OP))
    assert payments[0]["status"] == "REVERSED"


def test_dispute_after_approval_unwinds_paid_balance_to_zero(api):
    """PRD §2.9: "paid balance is conserved: Aggregator.paid_balance_cents always
    equals the sum of amount_cents over that aggregator's payments whose status is
    ISSUED or CLEARED; payments in REVERSED status are excluded."

    Design: Difficulty/compensating_invariant/aggregator_paid_balance_conserved_on_dispute
    """
    ctx = setup_approved_settlement(settlement_method="PAY_FOR_PERFORMANCE", event_load=4.0)
    get_success_data(api.dispute_settlement(ctx["set_id"], make_aggregator_headers(ctx["agg_id"])))
    after = validate_success(api.get_aggregator(ctx["agg_id"], OP))
    assert after["paid_balance_cents"] == 0, "invariant restored, no drift"


# --------------------------------------------------------------------------- #
# Corner: rbac / approve_same_user_sod_forbidden
# --------------------------------------------------------------------------- #
def test_dispatcher_cannot_approve_own_settlement(api):
    """PRD §3.7: "the acting operator's X-User-ID must differ from the settled
    event's dispatched_by_user_id — the operator who called the event may not
    approve its payout — else the request is refused with
    ERR_SEGREGATION_OF_DUTIES."

    Design: Corner/rbac/approve_same_user_sod_forbidden
    """
    ctx = setup_submitted_settlement(settlement_method="PAY_FOR_PERFORMANCE", event_load=4.0)
    # The event was notified (dispatched) by op1; approving as op1 violates SoD.
    resp = api.approve_settlement(ctx["set_id"], OP)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# --------------------------------------------------------------------------- #
# Corner: cross_cutting_complexity_layers / patch_program_stale_version_rejected
# --------------------------------------------------------------------------- #
def test_patch_program_with_stale_version_rejected(api):
    """PRD §2.6: "If expected_program_version does not equal the program's current
    version, the update is rejected with ERR_STALE_VERSION (HTTP 412): an earlier
    update has already advanced the program's version and legitimately superseded
    the configuration the client was working from, so the client's view is stale
    and its write must not silently overwrite the newer configuration."

    Design: Corner/cross_cutting_complexity_layers/patch_program_stale_version_rejected
    """
    prog = get_success_data(api.create_program(create_program_payload(name="P"), OP))
    v0 = prog["version"]
    get_success_data(api.update_program(
        prog["id"], {"expected_program_version": v0, "incentive_rate_cents_per_kwh": 55}, OP))
    resp = api.update_program(
        prog["id"], {"expected_program_version": v0, "incentive_rate_cents_per_kwh": 60}, OP)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# --------------------------------------------------------------------------- #
# Corner: cross_cutting_complexity_layers / mark_paid_clears_payments
# --------------------------------------------------------------------------- #
def test_mark_paid_clears_issued_payment_without_changing_balance(api):
    """PRD §3.7: "Marking paid clears the money: every payment of this settlement
    still in ISSUED status is moved to CLEARED. Because both ISSUED and CLEARED
    payments count toward an aggregator's paid_balance_cents, clearing does not
    change that balance."

    Design: Corner/cross_cutting_complexity_layers/mark_paid_clears_payments
    """
    ctx = setup_approved_settlement(settlement_method="PAY_FOR_PERFORMANCE", event_load=4.0)
    paid = validate_success(api.mark_paid_settlement(ctx["set_id"], OP))
    assert paid["status"] == "PAID"
    payments = get_success_data(api.list_settlement_payments(ctx["set_id"], OP))
    assert payments[0]["status"] == "CLEARED"
    agg = validate_success(api.get_aggregator(ctx["agg_id"], OP))
    assert agg["paid_balance_cents"] == 500, "CLEARED still counts toward the balance"
