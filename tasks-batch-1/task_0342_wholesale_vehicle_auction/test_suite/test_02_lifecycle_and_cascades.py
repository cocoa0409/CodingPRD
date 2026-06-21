"""Settlement parallel axes, IF-bid re-list cycle, transitive cascades, cross-entity
state dependencies, and conserved-quantity invariants across the auction lifecycle.
"""
import pytest

from test_helpers import (
    make_admin_headers, make_arbitrator_headers,
    get_success_data,
    setup_running_sale_with_lot, setup_hammered_lot, setup_cleared_settlement,
    setup_paid_settlement_with_open_claim, setup_two_proxy_hammered_lot,
    open_bidding, current_lot_version, place_bid_ok, get_settlement_for_lot,
    get_gate_pass_for_settlement,
)
import test_helpers as th


# ─── non_linear_state_machine ───────────────────────────────────────────────
def test_settlement_title_axis_advances_independently_of_payment_axis(api):
    """PRD §3.9: "The two axes advance independently — payment may precede title or vice versa."
    PRD §3.9: "it is `OPEN` while the settlement is neither paid-and-titled nor terminated;
    `CLEARED` once `payment_status` is `PAID` and `title_status` is `TITLE_RECEIVED`".

    Design: Difficulty/non_linear_state_machine/settlement_parallel_payment_and_title_axes
    """
    admin = make_admin_headers()
    ctx = setup_hammered_lot(api, admin, starting_bid_cents=400000, winning_amount_cents=800000,
                             channel="LANE")
    sid = ctx["settlement"]["id"]
    # Record title first; payment stays UNPAID, status stays OPEN.
    settlement = get_success_data(api.record_title(sid, admin))
    assert settlement["title_status"] == "TITLE_RECEIVED", settlement
    assert settlement["payment_status"] == "UNPAID", settlement
    assert settlement["status"] == "OPEN", settlement


def test_if_pending_consignment_relist_cycle_returns_to_run_listed(api):
    """PRD §3.6: "Re-listing moves a lot from `IF_PENDING` back to `SCHEDULED`".
    PRD §3.6: "Re-listing resets the lot's `high_bid_cents` to 0, `high_bidder_id` to null,
    and `outcome` to `NONE`, and cascades the consignment from `IF_PENDING` back to
    `RUN_LISTED`, so the vehicle can run again."

    Design: Difficulty/non_linear_state_machine/consignment_if_pending_relist_cycle
    """
    admin = make_admin_headers()
    # Reserve 900000; high bid 800000 (< reserve) -> outcome IF -> mark-if -> Consignment IF_PENDING.
    ctx = setup_running_sale_with_lot(api, admin, reserve_price_cents=900000, floor_price_cents=0,
                                      starting_bid_cents=400000)
    buyer = get_success_data(api.create_buyer(th.factories.create_buyer_payload(dealer_name="B1"), admin))
    lot_open = open_bidding(api, ctx["lot"]["id"], admin)
    place_bid_ok(api, ctx["lot"]["id"], buyer["id"], lot_open["version"],
                 bid_type="PROXY", amount_cents=800000, channel="LANE")
    get_success_data(api.close_bidding(ctx["lot"]["id"], admin))
    if_lot = get_success_data(api.mark_if(ctx["lot"]["id"], admin))
    assert if_lot["outcome"] == "IF", if_lot

    relisted = get_success_data(api.relist_lot(ctx["lot"]["id"], admin))
    assert relisted["status"] == "SCHEDULED", relisted
    assert relisted["high_bidder_id"] is None, relisted
    cons = get_success_data(api.get_consignment(ctx["consignment"]["id"], admin))
    assert cons["status"] == "RUN_LISTED", cons


# ─── transitive_cascade ─────────────────────────────────────────────────────
def test_payment_clears_settlement_finalizes_lot_issues_gatepass_settles_consignment(api):
    """PRD §3.9: "**Clearing** is a four-deep transitive cascade: the derived `status`
    becomes `CLEARED`; the settlement's `seller_proceeds_cents` is recomputed as the final
    seller-net-proceeds figure (§3.8) and mirrored onto the consignment's
    `expected_proceeds_cents`; the lot cascades from `HAMMERED` to `FINALIZED`; a gate pass
    is auto-issued in `ISSUED` status for the settlement and buyer (§3.10); and the
    consignment cascades from `SOLD` to `SETTLED`."

    Design: Difficulty/transitive_cascade/payment_clears_settlement_issues_gatepass_settles_consignment_depth4
    """
    admin = make_admin_headers()
    ctx = setup_hammered_lot(api, admin, starting_bid_cents=400000, winning_amount_cents=800000,
                             channel="LANE")
    sid = ctx["settlement"]["id"]
    # Record title first, THEN record payment so the single payment call triggers clearing.
    get_success_data(api.record_title(sid, admin))
    cleared = get_success_data(api.record_payment(sid, admin))

    assert cleared["status"] == "CLEARED", cleared
    lot = get_success_data(api.get_lot(ctx["lot"]["id"], admin))
    assert lot["status"] == "FINALIZED", lot
    gate_pass = get_gate_pass_for_settlement(api, sid, admin)
    assert gate_pass["status"] == "ISSUED", gate_pass
    cons = get_success_data(api.get_consignment(ctx["consignment"]["id"], admin))
    assert cons["status"] == "SETTLED", cons


def test_full_approval_arbitration_reverses_settlement_unwinds_consignment_and_lot(api):
    """PRD §3.10: "On `APPROVED_FULL`: the settlement is unwound".
    PRD §3.10: "The settlement's `payment_status` moves from `PAID` to `REVERSED` and its
    derived `status` becomes `VOID`; the buyer's `available_credit_cents` is re-credited by
    the full `total_due_cents` (recomputing `committed_cents`), fully returning the committed
    amount; the lot cascades from `HAMMERED` to `ARB_REVERSED`; the consignment cascades from
    `SOLD` to `ARB_UNWOUND`, with its `expected_proceeds_cents` set to 0".

    Design: Difficulty/transitive_cascade/arbitration_full_reverses_settlement_unwinds_consignment_depth3
    """
    admin = make_admin_headers()
    # Single-buyer hammer at 800000; claimed_cents >= sale_price -> APPROVED_FULL.
    ctx = setup_hammered_lot(api, admin, starting_bid_cents=400000, winning_amount_cents=800000,
                             channel="LANE")
    sid = ctx["settlement"]["id"]
    get_success_data(api.record_payment(sid, admin))
    claim = get_success_data(api.create_arbitration_claim(
        th.factories.create_arbitration_claim_payload(
            ctx["lot"]["id"], ctx["buyer"]["id"], reason_code="TITLE_DISCREPANCY", claimed_cents=800000),
        th.make_buyer_headers(ctx["buyer"]["id"]),
    ))
    ruled = get_success_data(api.rule_arbitration_claim(claim["id"], make_arbitrator_headers()))
    assert ruled["resolution"] == "APPROVED_FULL", ruled

    settlement = get_success_data(api.get_settlement(sid, admin))
    assert settlement["status"] == "VOID", settlement
    lot = get_success_data(api.get_lot(ctx["lot"]["id"], admin))
    assert lot["status"] == "ARB_REVERSED", lot
    cons = get_success_data(api.get_consignment(ctx["consignment"]["id"], admin))
    assert cons["status"] == "ARB_UNWOUND", cons


# ─── cross_entity_state_dependency ──────────────────────────────────────────
def test_open_bidding_requires_lane_active_after_sale_start(api):
    """PRD §3.5: "It requires the lot to be `SCHEDULED` (otherwise `ERR_LOT_NOT_SCHEDULED`),
    the owning sale to be `RUNNING` (otherwise `ERR_SALE_NOT_RUNNING`), and the referenced
    lane to be `ACTIVE` (otherwise `ERR_LANE_NOT_ACTIVE`)."
    PRD §3.1: "As a side effect of starting, every lane of the sale in `PLANNED`
    transitions to `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/lot_open_bidding_requires_lane_active
    """
    admin = make_admin_headers()
    ctx = setup_running_sale_with_lot(api, admin, reserve_price_cents=0, floor_price_cents=0,
                                      starting_bid_cents=400000)
    lane = get_success_data(api.get_lane(ctx["lane"]["id"], admin))
    assert lane["status"] == "ACTIVE", lane
    opened = get_success_data(api.open_bidding(ctx["lot"]["id"], admin))
    assert opened["status"] == "BIDDING_OPEN", opened


def test_arbitration_rule_requires_settlement_paid(api):
    """PRD §3.10: "Ruling requires the claim to be `OPEN` (otherwise `ERR_CLAIM_NOT_OPEN`)
    and the referenced lot's settlement to have `payment_status` of `PAID` (otherwise
    `ERR_SETTLEMENT_NOT_PAID`)."

    Design: Difficulty/cross_entity_state_dependency/arbitration_rule_requires_settlement_paid
    """
    admin = make_admin_headers()
    # Hammered lot, payment NOT recorded -> settlement UNPAID; open claim; rule -> ERR_SETTLEMENT_NOT_PAID.
    ctx = setup_hammered_lot(api, admin, starting_bid_cents=400000, winning_amount_cents=800000,
                             channel="LANE")
    claim = get_success_data(api.create_arbitration_claim(
        th.factories.create_arbitration_claim_payload(
            ctx["lot"]["id"], ctx["buyer"]["id"], reason_code="MECHANICAL", claimed_cents=100000),
        th.make_buyer_headers(ctx["buyer"]["id"]),
    ))
    resp = api.rule_arbitration_claim(claim["id"], make_arbitrator_headers())
    th.validate_error(resp, "ERR_SETTLEMENT_NOT_PAID")


# ─── compensating_invariant ─────────────────────────────────────────────────
def test_buyer_credit_conserved_across_hammer_and_full_arbitration_reversal(api):
    """PRD §2.10: "Striking a sale debits the winning buyer's available credit by exactly
    the lot's `total_due_cents`; the compensating reversal or write-off re-credits exactly
    that same `total_due_cents`, so credit is conserved end to end."

    Design: Difficulty/compensating_invariant/buyer_credit_conserved_across_hammer_and_arbitration_reversal
    """
    admin = make_admin_headers()
    ctx = setup_paid_settlement_with_open_claim(
        api, admin_headers=admin, claimed_cents=725000, reason_code="TITLE_DISCREPANCY",
        starting_bid_cents=600000, b1_ceiling=900000, b2_ceiling=700000, channel="ONLINE",
        buyer_fee_schedule_code="STANDARD", seller_fee_pct=0.02, b1_credit=2_000_000,
    )
    settlement = get_success_data(api.get_settlement(ctx["settlement"]["id"], admin))
    assert settlement["total_due_cents"] == 772850, settlement
    # claimed 725000 >= sale_price 725000 -> APPROVED_FULL -> full reversal re-credits 772850.
    get_success_data(api.rule_arbitration_claim(ctx["claim"]["id"], make_arbitrator_headers()))
    b1 = get_success_data(api.get_buyer(ctx["b1"]["id"], admin))
    assert b1["committed_cents"] == 0, b1
    assert b1["available_credit_cents"] == 2_000_000, b1


def test_lane_slot_count_conserved_across_lot_create_and_withdraw(api):
    """PRD §3.4: "A lane's `scheduled_slot_count` is, at all times, the number of lots in
    that lane whose status is neither `WITHDRAWN` nor `PASSED`. The count is maintained as a
    conserved running total: creating a lot increments it by one, and the compensating
    withdraw or pass of a lot decrements it by one".

    Design: Difficulty/compensating_invariant/lane_slot_count_conserved_across_lot_create_and_withdraw
    """
    admin = make_admin_headers()
    sale = get_success_data(api.create_sale(th.factories.create_sale_payload(), admin))
    lane = get_success_data(api.create_lane(th.factories.create_lane_payload(sale["id"]), admin))
    seller = get_success_data(api.create_seller(th.factories.create_seller_payload(), admin))
    cons1 = th.fixtures.make_cataloged_consignment(api, sale["id"], seller["id"], admin)
    cons2 = th.fixtures.make_cataloged_consignment(api, sale["id"], seller["id"], admin)
    th.fixtures.make_scheduled_lot(api, sale["id"], cons1["id"], lane["id"], admin,
                                   run_number=1, slot_start_minute=0, slot_end_minute=10)
    lot2 = th.fixtures.make_scheduled_lot(api, sale["id"], cons2["id"], lane["id"], admin,
                                          run_number=2, slot_start_minute=10, slot_end_minute=20)
    lane_before = get_success_data(api.get_lane(lane["id"], admin))
    assert lane_before["scheduled_slot_count"] == 2, lane_before

    withdrawn = get_success_data(api.withdraw_lot(lot2["id"], admin))
    assert withdrawn["status"] == "WITHDRAWN", withdrawn
    lane_after = get_success_data(api.get_lane(lane["id"], admin))
    assert lane_after["scheduled_slot_count"] == 1, lane_after


# ─── corner: state_machines & side effects ──────────────────────────────────
def test_write_off_defaults_settlement_recredits_and_suspends_buyer(api):
    """PRD §3.9: "It advances `payment_status` from `UNPAID` to `WRITTEN_OFF` and sets the
    derived `status` to `DEFAULTED`; it re-credits the buyer's `available_credit_cents` by
    the settlement's `total_due_cents` (recomputing `committed_cents`); and it suspends the
    buyer, moving the buyer from `ACTIVE` to `SUSPENDED`."

    Design: Corner/state_machines/write_off_suspends_buyer_and_recredits
    """
    admin = make_admin_headers()
    ctx = setup_hammered_lot(api, admin, starting_bid_cents=400000, winning_amount_cents=800000,
                             channel="LANE", credit_limit_cents=5_000_000)
    # Sale must be CLOSED for write-off precondition.
    get_success_data(api.close_sale(ctx["sale"]["id"], admin))
    written = get_success_data(api.write_off_settlement(ctx["settlement"]["id"], admin))
    assert written["status"] == "DEFAULTED", written
    assert written["payment_status"] == "WRITTEN_OFF", written
    buyer = get_success_data(api.get_buyer(ctx["buyer"]["id"], admin))
    assert buyer["status"] == "SUSPENDED", buyer
    assert buyer["available_credit_cents"] == 5_000_000, buyer


def test_terminal_settled_sale_rejects_close(api):
    """PRD §3.1: "Settling a sale moves it from `CLOSED` to `SETTLED`, the terminal state".
    PRD §3.1: "Closing a sale moves it from `RUNNING` to `CLOSED`; it requires the sale to
    be `RUNNING` (otherwise `ERR_SALE_NOT_RUNNING`)".

    Design: Corner/state_machines/terminal_settled_sale_rejects_further_transitions
    """
    admin = make_admin_headers()
    sale = get_success_data(api.create_sale(th.factories.create_sale_payload(), admin))
    get_success_data(api.create_lane(th.factories.create_lane_payload(sale["id"]), admin))
    get_success_data(api.open_sale(sale["id"], admin))
    get_success_data(api.start_sale(sale["id"], admin))
    get_success_data(api.close_sale(sale["id"], admin))
    get_success_data(api.settle_sale(sale["id"], admin))
    resp = api.close_sale(sale["id"], admin)
    th.validate_error(resp, "ERR_SALE_NOT_RUNNING")
