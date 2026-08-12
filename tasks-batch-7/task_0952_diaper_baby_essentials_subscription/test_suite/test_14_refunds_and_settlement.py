"""The cancellation refund formula, approval, denial, settlement and the clawback."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_credit_conserved,
    assert_cycle_cash_conserved,
    assert_points_ledger_conserved,
    assert_refund,
    list_points_entries,
    make_sku,
    make_subscription,
    read_credit,
    read_cycle,
    read_loyalty_account,
    read_refund,
    set_clock,
    setup_charged_cycle,
    setup_delivered_cycle,
    setup_dispatched_cycle,
    unique_code,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    activate,
    allocate_cycle,
    approve_refund,
    charge_cycle,
    claim_gift,
    generate_cycle,
    gift_credit_of,
    make_registry,
    make_registry_item,
    open_cycle_refund,
    pay_gift,
    refund_for_cycle,
    reserve_gift,
    setup_registry_parties,
    settle_refund,
)

OPS = TEST_USERS["ops_admin_headers"]
OPS2 = TEST_USERS["ops_admin_2_headers"]
SUPPORT = TEST_USERS["support_agent_headers"]


# ==========================================================================
# The dual-variant cancellation formula
# ==========================================================================
def test_a_dispatched_cycle_refund_is_prorated_and_carries_the_restock_fee(api):
    """PRD §3.10: "When the cycle's `status` is `DISPATCHED` or `DELIVERED`, the refund is
    prorated by the portion of the cycle the household has *not* yet used and then reduced by
    a restock fee of 600 cents, floored at 0, and `restock_fee_cents` records that 600. The
    used fraction is the number of whole days elapsed since the cycle's `dispatched_at` — that
    is, the difference between the logical clock and `dispatched_at` in seconds, divided by
    86400 and floored — divided by the subscription's `cadence_interval_days` at the moment of
    the cancellation, then clamped to lie between 0 and 1 inclusive. The refund is the cycle's
    `charged_cash_cents` multiplied by one minus that used fraction, rounded half up to whole
    cents *before* the 600-cent restock fee is subtracted, with the result floored at 0."

    Design: Difficulty/dual_variant_calc/cancel_refund_dispatched_prorated_vs_undispatched_full
    """
    ctx, cycle, _shipment = setup_dispatched_cycle(api, email_prefix="proration")
    assert cycle["charged_cash_cents"] == 2999
    set_clock(api, "2026-06-13T00:00:00Z")

    refund = validate_success(
        api.create_cycle_refund_request(cycle["id"], "CANCEL", ctx["headers"]), 201
    )
    assert_refund(refund)
    assert refund["requested_cents"] == 1649, (
        "round_half_up(2999 x 0.75) is 2249, less the 600-cent restock fee"
    )
    assert refund["restock_fee_cents"] == 600
    assert refund["status"] == "REQUESTED"


def test_an_undispatched_cycle_refund_returns_the_whole_charge(api):
    """PRD §3.10: "When the cycle's `status` is `PLANNED`, `ALLOCATED` or `CUTOFF_LOCKED`,
    the refund is the whole of the cycle's `charged_cash_cents` — no proration, and
    `restock_fee_cents` is 0."

    Design: Difficulty/dual_variant_calc/cancel_refund_dispatched_prorated_vs_undispatched_full
    """
    ctx, cycle = setup_charged_cycle(api, email_prefix="nopro")
    assert cycle["charged_cash_cents"] == 2999
    assert cycle["status"] == "ALLOCATED"

    refund = validate_success(
        api.create_cycle_refund_request(cycle["id"], "CANCEL", ctx["headers"]), 201
    )
    assert refund["requested_cents"] == 2999
    assert refund["restock_fee_cents"] == 0
    assert refund["status"] == "REQUESTED"


# ==========================================================================
# Approval, denial and settlement preconditions
# ==========================================================================
def test_settling_a_refund_that_was_never_approved_is_refused(api):
    """PRD §3.10: "Its `status` runs `REQUESTED`, `APPROVED`, `SETTLED` and `DENIED`, with
    `SETTLED` and `DENIED` terminal; any operation whose from-state does not match is refused
    with `ERR_REFUND_STATE_INVALID` (HTTP 409)."
    PRD §3.10: "Three preconditions apply: the refund must be `APPROVED`"

    Design: Corner/state_machines/corner_settle_refund_without_approval_rejected
    """
    ctx, cycle = setup_charged_cycle(api, email_prefix="settle")
    refund = open_cycle_refund(api, ctx["account_id"], cycle["id"])

    resp = api.settle_refund(refund["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_REFUND_STATE_INVALID.value, 409)

    after = read_refund(api, refund["id"])
    assert after["status"] == "REQUESTED"
    assert after["refunded_cash_cents"] == 0
    after_cycle = read_cycle(api, cycle["id"])
    assert after_cycle["retained_cash_cents"] == 2999
    assert after_cycle["payment_status"] == "CHARGED"


def test_the_approving_identity_may_not_also_settle(api):
    """PRD §2.1: "Finally, the platform enforces segregation of duties on money leaving the
    business. A `SupportAgent` approves a refund; an `OpsAdmin` or a second `SupportAgent`
    settles it. The `X-User-ID` performing the settlement must differ from the
    `approved_by_user_id` recorded at approval, and an attempt to settle a refund one has
    personally approved is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.10: "A `SupportAgent` approves a `REQUESTED` refund, moving it
    `REQUESTED → APPROVED` and recording their own `X-User-ID` as `approved_by_user_id`."

    Design: Corner/rbac/corner_same_agent_cannot_approve_and_settle_a_refund
    """
    ctx, cycle = setup_charged_cycle(api, email_prefix="sod")
    refund = open_cycle_refund(api, ctx["account_id"], cycle["id"])
    approved = validate_success(api.approve_refund(refund["id"], SUPPORT))
    assert approved["approved_by_user_id"] == "cs-1"

    resp = api.settle_refund(refund["id"], SUPPORT)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    after = read_refund(api, refund["id"])
    assert after["status"] == "APPROVED"
    assert after.get("settled_by_user_id") is None
    assert read_cycle(api, cycle["id"])["retained_cash_cents"] == 2999


def test_denying_a_refund_moves_no_money_and_no_points(api):
    """PRD §3.10: "The same role may instead deny it, moving it `REQUESTED → DENIED`, after
    which no money, no points and no credits move at all."

    Design: Corner/endpoints/corner_deny_refund_moves_no_money_or_points
    """
    ctx, cycle = setup_charged_cycle(api, email_prefix="deny")
    refund = open_cycle_refund(api, ctx["account_id"], cycle["id"])

    denied = validate_success(api.deny_refund(refund["id"], SUPPORT))
    assert denied["status"] == "DENIED"

    read_back = validate_success(api.get_refund(refund["id"], ctx["headers"]))
    assert read_back["refunded_cash_cents"] == 0

    after_cycle = read_cycle(api, cycle["id"])
    assert after_cycle["retained_cash_cents"] == 2999
    assert after_cycle["payment_status"] == "CHARGED"

    _entries, meta = validate_paginated(
        api.list_points_ledger_entries(
            ctx["headers"], {"loyalty_account_id": ctx["loyalty_account_id"]}
        )
    )
    assert meta["total_count"] == 0


def test_a_second_settlement_exceeding_the_retained_cash_is_refused(api):
    """PRD §3.10: "and the `requested_cents` may not exceed the cycle's `retained_cash_cents`
    for a Pipeline-R refund, or the gift's `paid_cents` for a Pipeline-G refund, or the request
    is refused with `ERR_REFUND_EXCEEDS_CHARGE` (HTTP 422)."
    PRD §3.10: "It decrements the cycle's `retained_cash_cents` by the refunded cash, which
    drives the cycle's payment axis: from `CHARGED` the cycle moves to `PARTIALLY_REFUNDED`
    when the refunded cash is less than `charged_cash_cents` and straight to `REFUNDED` when
    the two are equal"

    Design: Corner/validations/corner_second_prorated_refund_exceeds_retained_cash
    """
    ctx, cycle, _shipment = setup_dispatched_cycle(api, email_prefix="double")
    set_clock(api, "2026-06-13T00:00:00Z")

    first = open_cycle_refund(api, ctx["account_id"], cycle["id"])
    approve_refund(api, first["id"])
    settle_refund(api, first["id"])

    assert read_refund(api, first["id"])["refunded_cash_cents"] == 1649
    mid_cycle = read_cycle(api, cycle["id"])
    assert mid_cycle["retained_cash_cents"] == 1350
    assert mid_cycle["payment_status"] == "PARTIALLY_REFUNDED"

    second = open_cycle_refund(api, ctx["account_id"], cycle["id"])
    approve_refund(api, second["id"])
    resp = api.settle_refund(second["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_REFUND_EXCEEDS_CHARGE.value, 422)

    after = read_refund(api, second["id"])
    assert after["status"] == "APPROVED"
    assert after["refunded_cash_cents"] == 0


# ==========================================================================
# Gift credit is conserved and never restored
# ==========================================================================
def _cycle_part_paid_by_gift_credit(api):
    """A cycle charged for 1999 cash after 1000 cents of GIFT credit were consumed."""
    parties = setup_registry_parties(
        api,
        with_plan=True,
        sku_overrides={"code": unique_code("S2-GIFT"), "name": "Stage 2 Gift Pack",
                       "pack_price_cents": 1000, "stock_packs": 0},
    )
    make_sku(api, code=unique_code("S2-STD"), pack_price_cents=1200, stock_packs=50)

    registry = make_registry(api, parties, title="Conservation Registry")
    item = make_registry_item(api, parties, registry["id"], requested_quantity=1)
    validate_success(api.open_registry(registry["id"], parties["owner_headers"]))
    gift = reserve_gift(api, parties, item, 1)
    pay_gift(api, parties, gift["id"])
    claim_gift(api, parties, gift["id"], "CREDIT")
    credit = gift_credit_of(api, parties)

    subscription = make_subscription(api, parties["owner"], parties["plan"], parties["child"])
    subscription = activate(api, parties["owner_id"], subscription["id"])
    cycle = generate_cycle(api, subscription["id"])
    allocate_cycle(api, cycle["id"])
    cycle = charge_cycle(api, cycle["id"])
    return parties, credit, cycle


def test_a_settled_refund_never_restores_a_gift_credit(api):
    """PRD §3.10: "a credit whose `refundable` is false — which means every `GIFT` credit —
    restores nothing, its cents staying in `consumed_cents` permanently, and it is excluded
    from `credits_restored_cents` entirely. Gift credit consumed by a cycle that is later
    refunded is simply lost to the customer."
    PRD §2.9: "A credit's face value is conserved: for every `Credit` row, `issued_cents`
    always equals `consumed_cents` plus `remaining_cents` plus `forfeited_cents`."

    Design: Difficulty/compensating_invariant/gift_credit_money_conserved_and_never_restored_on_refund
    """
    parties, credit, cycle = _cycle_part_paid_by_gift_credit(api)
    assert cycle["gift_credit_applied_cents"] == 1000
    assert cycle["charged_cash_cents"] == 1999

    refund = open_cycle_refund(api, parties["owner_id"], cycle["id"])
    approve_refund(api, refund["id"])
    settled = settle_refund(api, refund["id"])

    assert settled["refunded_cash_cents"] == 1999
    assert settled["credits_restored_cents"] == 0

    after = read_credit(api, credit["id"], parties["owner_id"])
    assert after["issued_cents"] == 1000
    assert after["consumed_cents"] == 1000
    assert after["remaining_cents"] == 0
    assert after["forfeited_cents"] == 0
    assert after["status"] == "CONSUMED"
    assert_credit_conserved(after)


def test_the_settlement_drains_the_retained_cash_into_the_refund(api):
    """PRD §2.9: "Cycle cash is conserved: a `Cycle`'s `charged_cash_cents` always equals its
    `retained_cash_cents` plus the sum of `refunded_cash_cents` across every settled refund on
    that cycle."
    PRD §3.10: "It decrements the cycle's `retained_cash_cents` by the refunded cash, which
    drives the cycle's payment axis: from `CHARGED` the cycle moves to `PARTIALLY_REFUNDED`
    when the refunded cash is less than `charged_cash_cents` and straight to `REFUNDED` when
    the two are equal, and a later refund that exhausts what remains moves it
    `PARTIALLY_REFUNDED → REFUNDED`; reaching `REFUNDED` sets `retained_cash_cents` to 0."

    Design: Difficulty/compensating_invariant/gift_credit_money_conserved_and_never_restored_on_refund
    """
    parties, _credit, cycle = _cycle_part_paid_by_gift_credit(api)
    refund = open_cycle_refund(api, parties["owner_id"], cycle["id"])
    approve_refund(api, refund["id"])
    settled = settle_refund(api, refund["id"])

    after = read_cycle(api, cycle["id"])
    assert after["retained_cash_cents"] == 0
    assert after["payment_status"] == "REFUNDED"
    assert_cycle_cash_conserved(after, [settled])


# ==========================================================================
# The points clawback
# ==========================================================================
def _delivered_returned_and_approved(api, email_prefix):
    """A 50000-cent cycle delivered, its 500 points redeemed, then returned and approved."""
    ctx, cycle = setup_delivered_cycle(
        api,
        email_prefix=email_prefix,
        sku_overrides={"code": unique_code("S2-PREM"), "name": "Stage 2 Premium",
                       "pack_price_cents": 25000, "stock_packs": 10},
    )
    assert cycle["points_earned"] == 500
    validate_success(api.redeem_points(ctx["loyalty_account_id"], 500, ctx["headers"]), 201)
    validate_success(api.return_cycle(cycle["id"], OPS))

    refund = refund_for_cycle(api, cycle["id"])
    approve_refund(api, refund["id"])
    return ctx, cycle, refund


def test_the_clawback_drives_the_points_balance_negative(api):
    """PRD §3.10: "It writes exactly one `PointsLedgerEntry` with `entry_type` `CLAWBACK`,
    naming the refunded `cycle_id`, whose `delta_points` is the cycle's
    `loyalty_points_redeemed` minus its `points_earned` — a single signed movement that
    restores the redemption and removes the earning in one entry — and it records the cycle's
    `points_earned` on the refund as `points_clawed_back`. The wallet's `points_balance` is
    permitted to go negative as a result and no floor is applied."
    PRD §2.9: "The points ledger is conserved: a `LoyaltyAccount`'s `points_balance` always
    equals the sum of `delta_points` across every `PointsLedgerEntry` whose
    `loyalty_account_id` names that wallet."

    Design: Difficulty/compensating_invariant/points_ledger_conserved_and_balance_goes_negative_after_clawback
    """
    ctx, cycle, refund = _delivered_returned_and_approved(api, "ledger")
    settled = settle_refund(api, refund["id"])
    assert settled["points_clawed_back"] == 500

    wallet = read_loyalty_account(api, ctx["loyalty_account_id"])
    assert wallet["points_balance"] == -500

    entries = list_points_entries(api, ctx["loyalty_account_id"])
    assert len(entries) == 3, f"EARN, REDEEM and CLAWBACK, got {len(entries)}"
    assert sorted(e["delta_points"] for e in entries) == [-500, -500, 500]
    assert_points_ledger_conserved(wallet, entries)


def test_the_return_refund_uses_the_dispatched_variant_of_the_formula(api):
    """PRD §3.10: "An operator or the household may mark a `DISPATCHED` or `DELIVERED` cycle
    as returned. The cycle moves to `RETURNED`, the linked shipment is driven to `RETURNED`,
    and a `Refund` is opened in `REQUESTED` with `reason` `RETURN` and `requested_cents`
    computed under the dispatched variant of the formula above."
    PRD §2.9: "Cycle cash is conserved: a `Cycle`'s `charged_cash_cents` always equals its
    `retained_cash_cents` plus the sum of `refunded_cash_cents` across every settled refund on
    that cycle."

    Design: Difficulty/compensating_invariant/points_ledger_conserved_and_balance_goes_negative_after_clawback
    """
    ctx, cycle, refund = _delivered_returned_and_approved(api, "ledger2")
    settled = settle_refund(api, refund["id"])

    assert settled["refunded_cash_cents"] == 49400, "50000 charged, less the 600 restock fee"
    assert settled["restock_fee_cents"] == 600

    after = read_cycle(api, cycle["id"])
    assert after["retained_cash_cents"] == 600
    assert_cycle_cash_conserved(after, [settled])
