"""Compliance review of holds, dispute adjudication, and the resulting cascades.

Queue A: transitive_cascade/dispute_uphold_depth3_cascade,
transitive_cascade/riskhold_clear_depth2_cascade,
cross_entity_state_dependency/transfer_settle_depends_on_riskhold_cleared,
compensating_invariant/held_transfer_block_conserves_limit_usage,
dual_variant_calc/risk_score_update_increase_vs_decrease_on_account,
non_linear_state_machine/dispute_cyclic_open_needs_info_open_loop,
priority_pair_validation_conflict/segregation_safety_beats_invalid_state.
Queue B: errors (dispute on unsettled), validations (dispute window closed),
rbac (account holder cannot clear hold).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    make_account_holder_headers,
    make_compliance_officer_headers,
    create_account,
    make_recipient_verified,
    set_clock,
    seed_credit,
    send_transfer,
    create_settled_transfer,
    setup_held_transfer_scenario,
    setup_settled_transfer_pair,
    setup_open_dispute,
    open_dispute,
    create_dispute_payload,
    assert_risk_tier_matches_score,
)

OFFICER = make_compliance_officer_headers("officer-neutral")


# ===========================================================================
# Queue A — transitive_cascade / riskhold_clear_depth2_cascade
# ===========================================================================
def test_clear_hold_cascades_transfer_to_settled_and_credits_recipient(api):
    """PRD §3.4: "When the officer clears the hold, the `reviewer_user_id` is
    recorded and a cascade fires: the owning transfer moves from `HELD` to
    `SETTLED`. As part of that cascade the transfer's `settled_at` is stamped, a
    `CREDIT` ledger entry for `amount_cents` (source kind `TRANSFER`) is posted to
    the recipient, the sender's `held_balance_cents` drops by `amount_cents`, and
    the recipient's `available_balance_cents` is recomputed."

    Clearing the hold on a 100000c HELD transfer settles it, credits the recipient
    100000, drops sender held to 0 and lifts sender available to 400000.

    Design: Difficulty/transitive_cascade/riskhold_clear_depth2_cascade
    """
    sender, recipient, transfer, hold_id = setup_held_transfer_scenario(amount_cents=100000, sender_funded=500000)
    res = api.clear_risk_hold(hold_id, OFFICER)
    cleared = validate_success(res, 200)
    assert cleared["status"] == "CLEARED"

    t = validate_success(api.get_transfer(transfer["id"], make_account_holder_headers(sender["id"])), 200)
    assert t["status"] == "SETTLED"
    rec = validate_success(api.get_account(recipient["id"], make_account_holder_headers(recipient["id"])), 200)
    assert rec["available_balance_cents"] == 100000
    snd = validate_success(api.get_account(sender["id"], make_account_holder_headers(sender["id"])), 200)
    assert snd["held_balance_cents"] == 0
    assert snd["available_balance_cents"] == 400000


def test_clear_hold_terminal_cannot_clear_again(api):
    """PRD §3.4: "`CLEARED` is terminal."
    PRD §3.4: "Both review actions require the hold to be in `PENDING_REVIEW`"

    A second clear on a CLEARED hold is an invalid transition.

    Design: Difficulty/transitive_cascade/riskhold_clear_depth2_cascade
    """
    sender, recipient, transfer, hold_id = setup_held_transfer_scenario(amount_cents=100000, sender_funded=500000)
    validate_success(api.clear_risk_hold(hold_id, OFFICER), 200)
    res = api.clear_risk_hold(hold_id, OFFICER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Queue A — transitive_cascade / dispute_uphold_depth3_cascade
# ===========================================================================
def test_uphold_dispute_depth3_cascade(api):
    """PRD §3.8: "Upholding fires a depth-three cascade: a `Reversal` is created ...
    The disputed transfer is driven from `SETTLED` to `REVERSED`. A `DEBIT` ledger
    entry for `amount_cents` (source kind `REVERSAL`) is posted to the recipient to
    claw the funds back ... The recipient's `risk_score` is raised by 35 (the
    chargeback penalty) and their `risk_tier` re-derived, and both the opener's and
    recipient's `available_balance_cents` are recomputed."

    Upholding a dispute on a 2000c settled transfer reverses it, raises recipient
    risk_score to 35 (ELEVATED), and zeroes recipient available balance.

    Design: Difficulty/transitive_cascade/dispute_uphold_depth3_cascade
    """
    opener, recipient, transfer, dispute = setup_open_dispute(amount_cents=2000)
    res = api.uphold_dispute(dispute["id"], OFFICER)
    upheld = validate_success(res, 200)
    assert upheld["status"] == "UPHELD"

    t = validate_success(api.get_transfer(transfer["id"], make_account_holder_headers(opener["id"])), 200)
    assert t["status"] == "REVERSED"
    rec = validate_success(api.get_account(recipient["id"], make_account_holder_headers(recipient["id"])), 200)
    assert rec["risk_score"] == 35
    assert rec["risk_tier"] == "ELEVATED"
    assert_risk_tier_matches_score(rec)
    assert rec["available_balance_cents"] == 0


def test_uphold_creates_reversal_with_full_amount(api):
    """PRD §3.8: "a `Reversal` is created carrying the `transfer_id`, the
    `dispute_id` that authorized it, an `amount_cents` equal to the original
    transfer's `amount_cents` (a full reversal — no partial claw-backs), and a
    `status` of `APPLIED`; the dispute's `reversal_id` is set to it."

    The upheld dispute exposes a reversal_id; the reversal's amount_cents equals
    the original transfer amount and its status is APPLIED.

    Design: Difficulty/transitive_cascade/dispute_uphold_depth3_cascade
    """
    opener, recipient, transfer, dispute = setup_open_dispute(amount_cents=2000)
    upheld = validate_success(api.uphold_dispute(dispute["id"], OFFICER), 200)
    assert upheld["reversal_id"] is not None
    reversal = validate_success(api.get_reversal(upheld["reversal_id"], make_account_holder_headers(opener["id"])), 200)
    assert reversal["amount_cents"] == 2000
    assert reversal["status"] == "APPLIED"


# ===========================================================================
# Queue A — cross_entity_state_dependency / transfer_settle_depends_on_riskhold_cleared
# ===========================================================================
def test_held_transfer_reaches_settled_only_via_hold_clear(api):
    """PRD §3.4: "When the officer clears the hold, the `reviewer_user_id` is
    recorded and a cascade fires: the owning transfer moves from `HELD` to
    `SETTLED`."

    A HELD transfer becomes SETTLED as the side-effect of its owning RiskHold
    transitioning to CLEARED.

    Design: Difficulty/cross_entity_state_dependency/transfer_settle_depends_on_riskhold_cleared
    """
    sender, recipient, transfer, hold_id = setup_held_transfer_scenario(amount_cents=100000, sender_funded=500000)
    pre = validate_success(api.get_transfer(transfer["id"], make_account_holder_headers(sender["id"])), 200)
    assert pre["status"] == "HELD"
    cleared = validate_success(api.clear_risk_hold(hold_id, OFFICER), 200)
    assert cleared["status"] == "CLEARED"
    post = validate_success(api.get_transfer(transfer["id"], make_account_holder_headers(sender["id"])), 200)
    assert post["status"] == "SETTLED"


def test_held_transfer_cannot_be_cancelled_by_holder(api):
    """PRD §3.3: "A held transfer cannot be cancelled by the holder — it is resolved
    only through compliance review."

    Cancelling a HELD (risk_flagged) transfer is an invalid transition.

    Design: Difficulty/cross_entity_state_dependency/transfer_settle_depends_on_riskhold_cleared
    """
    sender, recipient, transfer, hold_id = setup_held_transfer_scenario(amount_cents=100000, sender_funded=500000)
    res = api.cancel_transfer(transfer["id"], make_account_holder_headers(sender["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Queue A — compensating_invariant / held_transfer_block_conserves_limit_usage
# ===========================================================================
def test_blocked_hold_rewinds_limit_usage(api):
    """PRD §3.4: "the sender's daily and weekly limit usage is rewound by
    `amount_cents` — the compensating inverse of the accumulation that the original
    hold performed."
    PRD §3.3: "Transfers that ended in `REVERSED` or `CANCELLED` are excluded from
    both sums"

    A 100000 HELD send accumulates usage; blocking reverses it, so a later 250000
    send (== full daily limit) succeeds, proving usage rewound to 0.

    Design: Difficulty/compensating_invariant/held_transfer_block_conserves_limit_usage
    """
    set_clock("2026-06-01T00:00:00.000Z")
    sender = create_account(funded_cents=600000, daily_send_limit_cents=250000,
                            weekly_send_limit_cents=5000000)
    recipient = create_account()
    make_recipient_verified(recipient["id"])
    held = validate_success(send_transfer(sender["id"], recipient["id"], 100000), 201)
    assert held["status"] == "HELD"
    validate_success(api.block_risk_hold(held["hold_id"], OFFICER), 200)

    follow = validate_success(send_transfer(sender["id"], recipient["id"], 250000), 201)
    assert follow["status"] == "HELD"  # 250000 >= LARGE_AMOUNT threshold, so also held
    snd = validate_success(api.get_account(sender["id"], make_account_holder_headers(sender["id"])), 200)
    # block refunded the 100000 (available back to 600000); the 250000 send then debits to held.
    assert snd["available_balance_cents"] == 350000


def test_blocked_hold_refunds_sender_balance(api):
    """PRD §3.4: "the owning transfer moves from `HELD` to `REVERSED`. A `CREDIT`
    ledger entry for `amount_cents` (source kind `REVERSAL`) is posted back to the
    sender to refund the earlier debit; the sender's `held_balance_cents` drops by
    `amount_cents` and `available_balance_cents` rises by `amount_cents`."

    Blocking a 100000c HELD transfer refunds the sender: available returns to its
    pre-send value and held drops to 0.

    Design: Difficulty/compensating_invariant/held_transfer_block_conserves_limit_usage
    """
    set_clock("2026-06-01T00:00:00.000Z")
    sender, recipient, transfer, hold_id = setup_held_transfer_scenario(amount_cents=100000, sender_funded=600000)
    validate_success(api.block_risk_hold(hold_id, OFFICER), 200)
    snd = validate_success(api.get_account(sender["id"], make_account_holder_headers(sender["id"])), 200)
    assert snd["available_balance_cents"] == 600000
    assert snd["held_balance_cents"] == 0
    t = validate_success(api.get_transfer(transfer["id"], make_account_holder_headers(sender["id"])), 200)
    assert t["status"] == "REVERSED"


# ===========================================================================
# Queue A — dual_variant_calc / risk_score_update_increase_vs_decrease_on_account
# ===========================================================================
def test_block_raises_then_deny_lowers_account_risk_score(api):
    """PRD §3.5: "When a risk hold on a sender is blocked, the sender's score rises
    by 20."
    PRD §3.5: "When a dispute is denied, the opener who raised it has their
    `risk_score` lowered by 10, with the result floored at 0 so it never goes
    negative."

    On one account O: a BLOCKED hold raises score to 20, then a DENIED dispute O
    opened lowers it to 10 (tier stays LOW).

    Design: Difficulty/dual_variant_calc/risk_score_update_increase_vs_decrease_on_account
    """
    set_clock("2026-06-01T00:00:00.000Z")
    opener = create_account(funded_cents=500000)
    recipient = create_account()
    make_recipient_verified(recipient["id"])
    # +20 via a BLOCKED hold on a LARGE_AMOUNT send
    held = validate_success(send_transfer(opener["id"], recipient["id"], 100000), 201)
    validate_success(api.block_risk_hold(held["hold_id"], OFFICER), 200)
    mid = validate_success(api.get_account(opener["id"], make_account_holder_headers(opener["id"])), 200)
    assert mid["risk_score"] == 20

    # a small SETTLED send O->R, then dispute it, then deny -> -10
    settled = create_settled_transfer(opener["id"], recipient["id"], 2000)
    dispute = open_dispute(settled["id"], opener["id"], "NOT_RECEIVED")
    validate_success(api.deny_dispute(dispute["id"], OFFICER), 200)
    final = validate_success(api.get_account(opener["id"], make_account_holder_headers(opener["id"])), 200)
    assert final["risk_score"] == 10
    assert final["risk_tier"] == "LOW"
    assert_risk_tier_matches_score(final)


def test_deny_dispute_floors_risk_score_at_zero(api):
    """PRD §3.5: "the opener who raised it has their `risk_score` lowered by 10,
    with the result floored at 0 so it never goes negative."

    Denying a dispute opened by an account already at risk_score 0 leaves it at 0
    (the -10 delta is floored).

    Design: Difficulty/dual_variant_calc/risk_score_update_increase_vs_decrease_on_account
    """
    opener, recipient, transfer, dispute = setup_open_dispute(amount_cents=2000, reason="DUPLICATE")
    before = validate_success(api.get_account(opener["id"], make_account_holder_headers(opener["id"])), 200)
    assert before["risk_score"] == 0
    validate_success(api.deny_dispute(dispute["id"], OFFICER), 200)
    after = validate_success(api.get_account(opener["id"], make_account_holder_headers(opener["id"])), 200)
    assert after["risk_score"] == 0
    assert after["risk_tier"] == "LOW"


# ===========================================================================
# Queue A — non_linear_state_machine / dispute_cyclic_open_needs_info_open_loop
# ===========================================================================
def test_dispute_request_info_then_provide_info_returns_to_open(api):
    """PRD §3.8: "A `ComplianceOfficer` may request more information on an `OPEN`
    dispute, moving it to `NEEDS_INFO` ... The opener may then provide information
    on a `NEEDS_INFO` dispute, moving it back to `OPEN`"

    OPEN -> NEEDS_INFO (request-info) -> OPEN (provide-info) is a true cycle.

    Design: Difficulty/non_linear_state_machine/dispute_cyclic_open_needs_info_open_loop
    """
    opener, recipient, transfer, dispute = setup_open_dispute(amount_cents=2000)
    ni = validate_success(api.request_info_dispute(dispute["id"], OFFICER), 200)
    assert ni["status"] == "NEEDS_INFO"
    back = validate_success(api.provide_info_dispute(dispute["id"], make_account_holder_headers(opener["id"])), 200)
    assert back["status"] == "OPEN"


def test_dispute_cycle_can_repeat(api):
    """PRD §3.8: "This cycle may repeat, forming an `OPEN ↔ NEEDS_INFO` loop."

    A second request-info/provide-info round-trip returns the dispute to OPEN again.

    Design: Difficulty/non_linear_state_machine/dispute_cyclic_open_needs_info_open_loop
    """
    opener, recipient, transfer, dispute = setup_open_dispute(amount_cents=2000)
    validate_success(api.request_info_dispute(dispute["id"], OFFICER), 200)
    validate_success(api.provide_info_dispute(dispute["id"], make_account_holder_headers(opener["id"])), 200)
    ni2 = validate_success(api.request_info_dispute(dispute["id"], OFFICER), 200)
    assert ni2["status"] == "NEEDS_INFO"
    back2 = validate_success(api.provide_info_dispute(dispute["id"], make_account_holder_headers(opener["id"])), 200)
    assert back2["status"] == "OPEN"


# ===========================================================================
# Queue A — priority_pair_validation_conflict / segregation_safety_beats_invalid_state
# ===========================================================================
def test_segregation_beats_invalid_state_on_terminal_dispute(api):
    """PRD §2.5: "(5) segregation of duties on compliance actions, surfacing
    `ERR_SEGREGATION_OF_DUTIES`; (6) the target being in a state from which the
    requested transition is defined, surfacing `ERR_INVALID_STATE`"
    PRD §2.4: "when an officer attempts to ... uphold ... a `Dispute`, the acting
    `X-User-ID` must not equal the sender or recipient `Account.id` of the
    underlying transfer ... A violation is rejected with
    `ERR_SEGREGATION_OF_DUTIES`"

    Re-upholding an already-UPHELD (terminal) dispute as the recipient party
    violates both p5 and p6; the lower-priority-number segregation check wins.

    Design: Difficulty/priority_pair_validation_conflict/segregation_safety_beats_invalid_state
    """
    opener, recipient, transfer, dispute = setup_open_dispute(amount_cents=2000)
    validate_success(api.uphold_dispute(dispute["id"], OFFICER), 200)  # now terminal UPHELD
    # recipient is a party -> segregation; dispute is terminal -> invalid state. p5 wins.
    res = api.uphold_dispute(dispute["id"], make_compliance_officer_headers(recipient["id"]))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_invalid_state_alone_on_terminal_dispute_with_neutral_officer(api):
    """PRD §2.5: "(6) the target being in a state from which the requested
    transition is defined, surfacing `ERR_INVALID_STATE`"

    A neutral officer re-upholding a terminal dispute fails on state alone (no
    segregation conflict), isolating the p6 check.

    Design: Difficulty/priority_pair_validation_conflict/segregation_safety_beats_invalid_state
    """
    opener, recipient, transfer, dispute = setup_open_dispute(amount_cents=2000)
    validate_success(api.uphold_dispute(dispute["id"], OFFICER), 200)
    res = api.uphold_dispute(dispute["id"], make_compliance_officer_headers("officer-neutral-2"))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Queue B — validations / errors: dispute window closed; dispute on unsettled
# ===========================================================================
def test_dispute_after_window_closed_rejected(api):
    """PRD §3.8: "A dispute may only be opened on a transfer that is `SETTLED` and
    only within 60 days of that transfer's `settled_at`: the current time must be at
    or before `settled_at` plus 60 days, inclusive. A dispute against a non-settled
    transfer, or one opened after the 60-day window has closed, is rejected with
    `ERR_DISPUTE_WINDOW_CLOSED`."

    Opening a dispute 3 months after settlement (>60d) is rejected.

    Design: Corner/validations/dispute_after_window_closed
    """
    set_clock("2026-06-01T00:00:00.000Z")
    opener, recipient, transfer = setup_settled_transfer_pair(amount_cents=2000, clock_iso=None)
    set_clock("2026-09-01T00:00:00.000Z")  # > 60 days later
    res = api.create_dispute(
        create_dispute_payload(transfer["id"], opener["id"], "UNAUTHORIZED"),
        make_account_holder_headers(opener["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED.value)


def test_dispute_on_unsettled_held_transfer_rejected(api):
    """PRD §3.8: "A dispute against a non-settled transfer, or one opened after the
    60-day window has closed, is rejected with `ERR_DISPUTE_WINDOW_CLOSED`."

    Opening a dispute on a HELD (non-SETTLED) transfer is rejected.

    Design: Corner/errors/dispute_on_unsettled_transfer_rejected
    """
    sender, recipient, transfer, hold_id = setup_held_transfer_scenario(amount_cents=100000, sender_funded=500000)
    res = api.create_dispute(
        create_dispute_payload(transfer["id"], sender["id"], "NOT_RECEIVED"),
        make_account_holder_headers(sender["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED.value)


# ===========================================================================
# Queue B — rbac: account holder cannot clear a risk hold
# ===========================================================================
def test_account_holder_cannot_clear_risk_hold(api):
    """PRD §2.1: "A request that is authenticated but whose role is not permitted to
    perform the requested operation is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Clearing a risk hold is a ComplianceOfficer-exclusive op; an AccountHolder is
    rejected with ERR_FORBIDDEN_ROLE.

    Design: Corner/rbac/account_holder_cannot_clear_risk_hold
    """
    sender, recipient, transfer, hold_id = setup_held_transfer_scenario(amount_cents=100000, sender_funded=500000)
    res = api.clear_risk_hold(hold_id, make_account_holder_headers(sender["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
