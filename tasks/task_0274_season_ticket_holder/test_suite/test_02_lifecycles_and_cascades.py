"""Subscription / transfer / payment-plan lifecycles and their cascades
(PRD §3.5, §3.6, §3.9, §3.10).

Covers the cyclic relocation flow, the forward-vs-resale branch fork, and the
depth-2 / depth-3 cascade chains, plus the invalid/terminal-state guards.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_active_subscription,
    setup_active_subscription_with_payment_plan,
    setup_pending_forward,
    setup_listed_resale,
    setup_relocating_subscription,
    list_plan_installments,
    make_account_holder_headers,
    TEST_USERS,
)

_BOX = TEST_USERS["box_office_headers"]
_FIN = TEST_USERS["finance_headers"]


# =========================================================================
# Non-linear state machine: relocation cycle ACTIVE -> RELOCATING -> ACTIVE
# =========================================================================
def test_relocation_cycle_returns_to_active(api):
    """PRD §3.5: "Beginning a relocation ... moves the subscription from `ACTIVE`
    to `RELOCATING` while incrementing its `version`; no seats change yet."
    PRD §3.5: "The season is then repriced, resetting `locked_price_cents` and
    `seat_count`, and the subscription returns to `ACTIVE` with its `version`
    incremented once more."

    Design: Difficulty/non_linear_state_machine/subscription_relocation_cycle_active_relocating_active
    """
    ctx = setup_relocating_subscription(target_seat_count=1, target_in_same_section=True)
    assert ctx["subscription"]["status"] == "RELOCATING", ctx["subscription"]["status"]
    target_id = ctx["targets"][0]["id"]
    resp = api.relocate_confirm(ctx["subscription"]["id"], {"target_seat_ids": [target_id]}, _BOX)
    sub = validate_success(resp)
    assert sub["status"] == "ACTIVE", sub["status"]


def test_relocation_confirm_swaps_seat_inventory(api):
    """PRD §3.5: "the current `ASSIGNED` assignments are released — their status
    becomes `REASSIGNED`, their seats return to `AVAILABLE` ... while a new
    `SeatAssignment` is created for each target seat, those seats become `SOLD`."

    The original seat returns to AVAILABLE and the relocation target becomes SOLD,
    demonstrating re-entry to ACTIVE leaves consistent inventory.

    Design: Difficulty/non_linear_state_machine/subscription_relocation_cycle_active_relocating_active
    """
    ctx = setup_relocating_subscription(target_seat_count=1, target_in_same_section=True)
    original_seat_id = ctx["seat"]["id"]
    target_id = ctx["targets"][0]["id"]
    validate_success(api.relocate_confirm(ctx["subscription"]["id"], {"target_seat_ids": [target_id]}, _BOX))
    orig = validate_success(api.get_seat(original_seat_id, _BOX))
    tgt = validate_success(api.get_seat(target_id, _BOX))
    assert orig["status"] == "AVAILABLE", orig["status"]
    assert tgt["status"] == "SOLD", tgt["status"]


# =========================================================================
# Branch fork: FORWARD vs RESALE divergent side-effects
# =========================================================================
def test_forward_branch_ends_forwarded_with_zero_payout(api):
    """PRD §3.9: "the transfer moves to `FORWARDED`, the seat assignment is
    reassigned into the recipient's active subscription context, no money changes
    hands, and `payout_cents` stays 0."

    Design: Difficulty/non_linear_state_machine/ticket_transfer_branch_forward_vs_listed_divergent_effects
    """
    ctx = setup_pending_forward()
    holder_headers = make_account_holder_headers(ctx["account"]["id"])
    resp = api.forward_ticket_transfer(ctx["transfer"]["id"], holder_headers)
    tt = validate_success(resp)
    assert tt["status"] == "FORWARDED", tt["status"]
    assert tt["payout_cents"] == 0, tt["payout_cents"]


def test_resale_branch_ends_sold_with_computed_payout(api):
    """PRD §3.9: "On completion the system computes the seller's payout, sets
    `payout_cents`, drives the original `SeatAssignment` to `REASSIGNED`, decrements
    the seller subscription's `seat_count`, and moves the transfer to `SOLD`."

    The RESALE branch (PENDING -> LISTED -> SOLD) diverges from FORWARD: gross=20000
    -> payout 17920, not 0.

    Design: Difficulty/non_linear_state_machine/ticket_transfer_branch_forward_vs_listed_divergent_effects
    """
    ctx = setup_listed_resale(listing_price_cents=20000)
    resp = api.complete_sale(ctx["transfer"]["id"], {"recipient_account_id": ctx["buyer"]["id"]}, _BOX)
    tt = validate_success(resp)
    assert tt["status"] == "SOLD", tt["status"]
    assert tt["payout_cents"] == 17920, tt["payout_cents"]


# =========================================================================
# Transitive cascade depth-3: cancel -> plan CANCELLED -> installments VOID
# =========================================================================
def test_cancel_cascades_plan_to_cancelled(api):
    """PRD §3.6: "any `ACTIVE` `PaymentPlan` for the subscription transitions to
    `CANCELLED`, which voids each of its `SCHEDULED` `Installment` rows to `VOID`."

    Design: Difficulty/transitive_cascade/cancel_cascades_subscription_plan_installments_depth3
    """
    ctx = setup_active_subscription_with_payment_plan(installment_count=4, base_price_cents=200000)
    sub = validate_success(api.cancel_subscription(ctx["subscription"]["id"], _BOX))
    assert sub["status"] == "CANCELLED", sub["status"]
    plan = validate_success(api.get_payment_plan(ctx["payment_plan"]["id"], _FIN))
    assert plan["status"] == "CANCELLED", plan["status"]


def test_cancel_cascades_installments_to_void(api):
    """PRD §3.6: "any `ACTIVE` `PaymentPlan` for the subscription transitions to
    `CANCELLED`, which voids each of its `SCHEDULED` `Installment` rows to `VOID`."

    Every SCHEDULED installment under the cancelled plan ends VOID (depth-3 hop:
    cancel -> plan CANCELLED -> installments VOID).

    Design: Difficulty/transitive_cascade/cancel_cascades_subscription_plan_installments_depth3
    """
    ctx = setup_active_subscription_with_payment_plan(installment_count=4, base_price_cents=200000)
    validate_success(api.cancel_subscription(ctx["subscription"]["id"], _BOX))
    rows = list_plan_installments(ctx["payment_plan"]["id"])
    assert len(rows) == 4, len(rows)
    assert all(r["status"] == "VOID" for r in rows), [r["status"] for r in rows]


# =========================================================================
# Transitive cascade depth-2: default -> subscription SUSPENDED
# =========================================================================
def test_default_sets_plan_defaulted(api):
    """PRD §3.10: "Declaring a default is also a finance-clerk action, legal only
    while the plan is `ACTIVE` and at least one installment is still `SCHEDULED`;
    it moves the plan to `DEFAULTED` and, as a cascade, transitions the financed
    subscription from `ACTIVE` to `SUSPENDED`, freezing its seat assignments."

    Design: Difficulty/transitive_cascade/default_cascades_paymentplan_subscription_suspended_depth2
    """
    ctx = setup_active_subscription_with_payment_plan(installment_count=4, base_price_cents=200000)
    plan = validate_success(api.default_payment_plan(ctx["payment_plan"]["id"], _FIN))
    assert plan["status"] == "DEFAULTED", plan["status"]


def test_default_cascades_subscription_to_suspended(api):
    """PRD §3.10: "it moves the plan to `DEFAULTED` and, as a cascade, transitions
    the financed subscription from `ACTIVE` to `SUSPENDED`, freezing its seat
    assignments."

    Design: Difficulty/transitive_cascade/default_cascades_paymentplan_subscription_suspended_depth2
    """
    ctx = setup_active_subscription_with_payment_plan(installment_count=4, base_price_cents=200000)
    validate_success(api.default_payment_plan(ctx["payment_plan"]["id"], _FIN))
    sub = validate_success(api.get_subscription(ctx["subscription"]["id"], _BOX))
    assert sub["status"] == "SUSPENDED", sub["status"]


# =========================================================================
# Corner — state machines: invalid / terminal transitions
# =========================================================================
def test_activate_already_active_rejected(api):
    """PRD §2.9: "when a transition is requested against a resource whose current
    state is not a legal source for that transition — activation against a
    subscription that is not `PENDING` ... the request is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/activate_already_active_subscription_returns_invalid_state
    """
    ctx = setup_active_subscription()
    resp = api.activate_subscription(ctx["subscription"]["id"], _BOX)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_activate_with_no_assigned_seats_rejected(api):
    """PRD §3.3: "Activation, performed by a box office agent, is legal only while
    the subscription is `PENDING`, requires the holder `Account` to be `ACTIVE`, and
    requires at least one `SeatAssignment` in `ASSIGNED` status to exist for it."

    A PENDING subscription with zero seat assignments cannot activate.

    Design: Corner/state_machines/activate_subscription_with_no_assigned_seats_returns_invalid_state
    """
    from test_helpers import create_account, create_season_plan, create_subscription
    account = create_account()
    plan = create_season_plan(plan_type="FULL", price_multiplier_bps=10000)
    sub = create_subscription(account["id"], plan["id"])
    resp = api.activate_subscription(sub["id"], _BOX)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_already_cancelled_rejected(api):
    """PRD §2.9: "A `Subscription` is terminal once `CANCELLED`. ... Attempting to
    drive any resource out of a terminal state is rejected with
    `ERR_VALIDATION_FROM_TERMINAL` (HTTP 409)."

    Design: Corner/state_machines/cancel_already_cancelled_subscription_returns_invalid_state
    """
    ctx = setup_active_subscription()
    validate_success(api.cancel_subscription(ctx["subscription"]["id"], _BOX))
    resp = api.cancel_subscription(ctx["subscription"]["id"], _BOX)
    validate_error(resp, ApiErrorId.ERR_VALIDATION_FROM_TERMINAL.value)


def test_relocate_confirm_without_begin_rejected(api):
    """PRD §2.9: "when a transition is requested against a resource whose current
    state is not a legal source for that transition — ... a relocation confirm
    against one that is not `RELOCATING` ... the request is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/relocate_confirm_from_active_without_begin_returns_invalid_state
    """
    ctx = setup_active_subscription()
    target = _make_available_seat(api, ctx["section"]["id"])
    resp = api.relocate_confirm(ctx["subscription"]["id"], {"target_seat_ids": [target["id"]]}, _BOX)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_complete_sale_before_list_rejected(api):
    """PRD §2.9: "when a transition is requested against a resource whose current
    state is not a legal source for that transition — ... a sale completion against
    a transfer that is not `LISTED` ... the request is rejected with
    `ERR_INVALID_STATE` (HTTP 409)."

    A RESALE transfer still PENDING (never listed) cannot complete-sale.

    Design: Corner/state_machines/complete_sale_before_list_returns_invalid_state
    """
    from test_helpers import create_account
    ctx = setup_active_subscription()
    holder_headers = make_account_holder_headers(ctx["account"]["id"])
    buyer = create_account(full_name="Buyer CS")
    transfer = validate_success(
        api.create_ticket_transfer(
            {"seat_assignment_id": ctx["assignment"]["id"], "transfer_type": "RESALE",
             "listing_price_cents": 20000},
            holder_headers,
        ),
        expected_status=201,
    )
    resp = api.complete_sale(transfer["id"], {"recipient_account_id": buyer["id"]}, _BOX)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_pay_all_installments_closes_plan(api):
    """PRD §3.10: "paying drives that installment to `PAID` and adds its
    `amount_cents` to the plan's `amount_paid_cents`. ... When the installment being
    paid is the only remaining `SCHEDULED` one, paying it additionally moves the
    plan to the terminal `PAID_IN_FULL` state."

    Paying all four installments of a 200000 plan ([50000,50000,50000,50000]) drives
    amount_paid_cents to 200000 and status to PAID_IN_FULL.

    Design: Corner/state_machines/pay_installment_records_payment_and_closes_plan
    """
    ctx = setup_active_subscription_with_payment_plan(installment_count=4, base_price_cents=200000)
    plan_id = ctx["payment_plan"]["id"]
    for seq in (1, 2, 3):
        validate_success(api.pay_installment(plan_id, seq, _FIN))
    last = validate_success(api.pay_installment(plan_id, 4, _FIN))
    assert last["status"] == "PAID", last["status"]
    plan = validate_success(api.get_payment_plan(plan_id, _FIN))
    assert plan["amount_paid_cents"] == 200000, plan["amount_paid_cents"]
    assert plan["status"] == "PAID_IN_FULL", plan["status"]


# --- helper local to this file ---
def _make_available_seat(api, section_id):
    from test_helpers import create_seat_payload
    return validate_success(
        api.create_seat(create_seat_payload(section_id, row_label="Z", seat_number=99), _BOX),
        expected_status=201,
    )
