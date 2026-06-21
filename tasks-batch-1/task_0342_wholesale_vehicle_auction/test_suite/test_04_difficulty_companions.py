"""Second tests for every difficulty-design instance.

Each test here re-exercises the same design instance as its counterpart in
test_01..test_03, but pins a DIFFERENT observable consequence of the same PRD rule
(a sibling field, the complementary axis, or an adjacent boundary), so the assertion
is independently meaningful rather than a duplicate.
"""
import pytest

from test_helpers import (
    make_admin_headers, make_buyer_headers, make_arbitrator_headers,
    get_success_data, validate_error,
    setup_running_sale_with_lot, setup_hammered_lot, setup_two_proxy_hammered_lot,
    setup_paid_settlement_with_open_claim, setup_cleared_settlement,
    open_bidding, current_lot_version, place_bid, place_bid_ok, get_settlement_for_lot,
    get_gate_pass_for_settlement,
)
import test_helpers as th


# ─── dual_variant_calc (companions) ─────────────────────────────────────────
def test_provisional_buyer_fee_and_total_due_set_at_hammer_before_arbitration(api):
    """PRD §3.6: "computing its provisional `sale_price_cents` (equal to `hammer_price_cents`),
    `buyer_fee_cents`, `total_due_cents`, and `seller_proceeds_cents`".
    PRD §2.8: "A **provisional** figure is computed the moment a sale is struck, from the
    hammer price."

    Design: Difficulty/dual_variant_calc/buyer_fee_provisional_vs_final_after_partial_arbitration
    """
    admin = make_admin_headers()
    ctx = setup_two_proxy_hammered_lot(
        api, admin, starting_bid_cents=600000, b1_ceiling=900000, b2_ceiling=700000,
        channel="ONLINE", buyer_fee_schedule_code="STANDARD", seller_fee_pct=0.02)
    settlement = get_success_data(api.get_settlement(ctx["settlement"]["id"], admin))
    # Provisional: S=725000, fee 47850, total_due 772850 — frozen before any ruling.
    assert settlement["sale_price_cents"] == 725000, settlement
    assert settlement["buyer_fee_cents"] == 47850, settlement
    assert settlement["total_due_cents"] == 772850, settlement


def test_partial_arbitration_marks_resolution_and_approved_cents(api):
    """PRD §3.10: "if the `claimed_cents` is at most the cap, `approved_cents` equals the
    `claimed_cents` and the `resolution` is `APPROVED_PARTIAL`".
    PRD §2.8: "A **final** figure is recomputed later if the economics change: specifically
    when an arbitration ruling reduces the effective sale price."

    Design: Difficulty/dual_variant_calc/seller_proceeds_provisional_vs_final_after_partial_arbitration
    """
    admin = make_admin_headers()
    ctx = setup_paid_settlement_with_open_claim(
        api, admin_headers=admin, claimed_cents=100000, reason_code="MECHANICAL",
        starting_bid_cents=600000, b1_ceiling=900000, b2_ceiling=700000, channel="ONLINE",
        buyer_fee_schedule_code="STANDARD", seller_fee_pct=0.02)
    ruled = get_success_data(api.rule_arbitration_claim(ctx["claim"]["id"], make_arbitrator_headers()))
    assert ruled["resolution"] == "APPROVED_PARTIAL", ruled
    assert ruled["approved_cents"] == 100000, ruled


# ─── combinatorial_formula (companions) ─────────────────────────────────────
def test_single_proxy_clearing_only_needs_to_beat_house_floor(api):
    """PRD §3.5: "If exactly one buyer has bid, with ceiling C1, then `high_bidder_id` is
    that buyer and `high_bid_cents` is the lesser of C1 and the greater of the house floor
    and the lot's `starting_bid_cents` — that is, the single bidder need only beat the house
    floor, and the standing price never rises above that bidder's own ceiling."

    Design: Difficulty/combinatorial_formula/clearing_price_nested_min_max_three_inputs
    """
    admin = make_admin_headers()
    # starting_bid 500000, floor 0 -> house_floor 500000; single PROXY 1000000.
    # clearing = min(1000000, max(500000, 500000)) = 500000.
    ctx = setup_running_sale_with_lot(api, admin, reserve_price_cents=0, floor_price_cents=0,
                                      starting_bid_cents=500000)
    buyer = get_success_data(api.create_buyer(th.factories.create_buyer_payload(dealer_name="B1"), admin))
    lot_open = open_bidding(api, ctx["lot"]["id"], admin)
    place_bid_ok(api, ctx["lot"]["id"], buyer["id"], lot_open["version"],
                 bid_type="PROXY", amount_cents=1000000, channel="ONLINE")
    lot = get_success_data(api.get_lot(ctx["lot"]["id"], admin))
    assert lot["high_bid_cents"] == 500000, lot
    assert lot["high_bidder_id"] == buyer["id"], lot


def test_buyer_fee_cents_is_base_plus_online_surcharge(api):
    """PRD §3.7: "The `buyer_fee_cents` is the base plus the surcharge."
    PRD §3.7: "for a sale price from 200000 up to but not including 1000000 the base is 6%
    of the sale price, rounded half up to cents".

    Design: Difficulty/combinatorial_formula/buyer_total_due_rounding_order_per_term_then_sum
    """
    admin = make_admin_headers()
    # Single PROXY 300000 ONLINE, starting_bid 200008 -> S=200008; base 12000, surcharge 1200, fee 13200.
    ctx = setup_running_sale_with_lot(api, admin, reserve_price_cents=0, floor_price_cents=0,
                                      starting_bid_cents=200008, buyer_fee_schedule_code="STANDARD",
                                      seller_fee_pct=0.02)
    buyer = get_success_data(api.create_buyer(th.factories.create_buyer_payload(dealer_name="B1"), admin))
    lot_open = open_bidding(api, ctx["lot"]["id"], admin)
    place_bid_ok(api, ctx["lot"]["id"], buyer["id"], lot_open["version"],
                 bid_type="PROXY", amount_cents=300000, channel="ONLINE")
    get_success_data(api.close_bidding(ctx["lot"]["id"], admin))
    get_success_data(api.hammer_lot(ctx["lot"]["id"], admin))
    settlement = get_settlement_for_lot(api, ctx["lot"]["id"], admin)
    assert settlement["sale_price_cents"] == 200008, settlement
    assert settlement["buyer_fee_cents"] == 13200, settlement


# ─── non_linear_state_machine (companions) ──────────────────────────────────
def test_settlement_payment_axis_advances_independently_of_title_axis(api):
    """PRD §3.9: "The two axes advance independently — payment may precede title or vice versa."
    PRD §3.9: "it is `OPEN` while the settlement is neither paid-and-titled nor terminated".

    Design: Difficulty/non_linear_state_machine/settlement_parallel_payment_and_title_axes
    """
    admin = make_admin_headers()
    ctx = setup_hammered_lot(api, admin, starting_bid_cents=400000, winning_amount_cents=800000,
                             channel="LANE")
    sid = ctx["settlement"]["id"]
    settlement = get_success_data(api.record_payment(sid, admin))
    assert settlement["payment_status"] == "PAID", settlement
    assert settlement["title_status"] == "PENDING_TITLE", settlement
    assert settlement["status"] == "OPEN", settlement


def test_mark_if_cascades_consignment_to_if_pending(api):
    """PRD §3.6: "**Marking if-bid** sets the lot's `outcome` to `IF` and cascades the
    consignment from `RUN_LISTED` to `IF_PENDING`."

    Design: Difficulty/non_linear_state_machine/consignment_if_pending_relist_cycle
    """
    admin = make_admin_headers()
    ctx = setup_running_sale_with_lot(api, admin, reserve_price_cents=900000, floor_price_cents=0,
                                      starting_bid_cents=400000)
    buyer = get_success_data(api.create_buyer(th.factories.create_buyer_payload(dealer_name="B1"), admin))
    lot_open = open_bidding(api, ctx["lot"]["id"], admin)
    place_bid_ok(api, ctx["lot"]["id"], buyer["id"], lot_open["version"],
                 bid_type="PROXY", amount_cents=800000, channel="LANE")
    get_success_data(api.close_bidding(ctx["lot"]["id"], admin))
    get_success_data(api.mark_if(ctx["lot"]["id"], admin))
    cons = get_success_data(api.get_consignment(ctx["consignment"]["id"], admin))
    assert cons["status"] == "IF_PENDING", cons


# ─── transitive_cascade (companions) ────────────────────────────────────────
def test_clearing_mirrors_final_proceeds_onto_consignment(api):
    """PRD §3.9: "the settlement's `seller_proceeds_cents` is recomputed as the final
    seller-net-proceeds figure (§3.8) and mirrored onto the consignment's
    `expected_proceeds_cents`".

    Design: Difficulty/transitive_cascade/payment_clears_settlement_issues_gatepass_settles_consignment_depth4
    """
    admin = make_admin_headers()
    # Single-buyer hammer at 800000 LANE, seller_fee_pct 0.02. Per §3.5 a single bidder
    # clears at the greater of the house floor and starting_bid, capped by its own ceiling:
    # house_floor = max(starting_bid=800000, floor=0) = 800000; clearing = min(800000, 800000)
    # = 800000. proceeds = 800000 - round(800000*0.02)=16000 - 5000 = 779000.
    ctx = setup_hammered_lot(api, admin, starting_bid_cents=800000, winning_amount_cents=800000,
                             channel="LANE", seller_fee_pct=0.02)
    sid = ctx["settlement"]["id"]
    get_success_data(api.record_payment(sid, admin))
    cleared = get_success_data(api.record_title(sid, admin))
    assert cleared["seller_proceeds_cents"] == 779000, cleared
    cons = get_success_data(api.get_consignment(ctx["consignment"]["id"], admin))
    assert cons["expected_proceeds_cents"] == 779000, cons


def test_full_approval_voids_gatepass(api):
    """PRD §3.10: "if a gate pass exists for the settlement in `ISSUED` status, it is voided,
    moving from `ISSUED` to `VOID`."

    Design: Difficulty/transitive_cascade/arbitration_full_reverses_settlement_unwinds_consignment_depth3
    """
    admin = make_admin_headers()
    # Clear the settlement first (payment + title) so a gate pass is ISSUED, then full-approve.
    # (claimed_cents >= sale_price -> APPROVED_FULL.)
    ctx = setup_cleared_settlement(api, admin, starting_bid_cents=400000, winning_amount_cents=800000,
                                   channel="LANE")
    sid = ctx["settlement"]["id"]
    gate_pass = ctx["gate_pass"]
    claim = get_success_data(api.create_arbitration_claim(
        th.factories.create_arbitration_claim_payload(
            ctx["lot"]["id"], ctx["buyer"]["id"], reason_code="TITLE_DISCREPANCY", claimed_cents=800000),
        make_buyer_headers(ctx["buyer"]["id"]),
    ))
    get_success_data(api.rule_arbitration_claim(claim["id"], make_arbitrator_headers()))
    gp = get_success_data(api.get_gate_pass(gate_pass["id"], admin))
    assert gp["status"] == "VOID", gp


# ─── cross_entity_state_dependency (companions) ─────────────────────────────
def test_open_bidding_initializes_high_bid_to_house_floor(api):
    """PRD §3.5: "On opening, the lot's standing high bid is initialized: `high_bid_cents` is
    set to the greater of the lot's `starting_bid_cents` and the consignment's
    `floor_price_cents`, and `high_bidder_id` is set to null".

    Design: Difficulty/cross_entity_state_dependency/lot_open_bidding_requires_lane_active
    """
    admin = make_admin_headers()
    # starting_bid 400000, floor 450000 -> high_bid initialized to 450000, high_bidder null.
    ctx = setup_running_sale_with_lot(api, admin, reserve_price_cents=500000, floor_price_cents=450000,
                                      starting_bid_cents=400000)
    opened = get_success_data(api.open_bidding(ctx["lot"]["id"], admin))
    assert opened["high_bid_cents"] == 450000, opened
    assert opened["high_bidder_id"] is None, opened


def test_arbitration_rule_succeeds_once_settlement_paid(api):
    """PRD §3.10: "Ruling requires the claim to be `OPEN` (otherwise `ERR_CLAIM_NOT_OPEN`)
    and the referenced lot's settlement to have `payment_status` of `PAID`".
    PRD §3.10: "An `Arbitrator` rules on a claim, moving it from `OPEN` to `RESOLVED` (the
    terminal state)."

    Design: Difficulty/cross_entity_state_dependency/arbitration_rule_requires_settlement_paid
    """
    admin = make_admin_headers()
    ctx = setup_paid_settlement_with_open_claim(
        api, admin_headers=admin, claimed_cents=100000, reason_code="MECHANICAL",
        starting_bid_cents=600000, b1_ceiling=900000, b2_ceiling=700000, channel="ONLINE")
    ruled = get_success_data(api.rule_arbitration_claim(ctx["claim"]["id"], make_arbitrator_headers()))
    assert ruled["status"] == "RESOLVED", ruled


# ─── priority_pair_validation_conflict (companions) ─────────────────────────
def test_insufficient_credit_fires_when_lot_is_bidding_open(api):
    """PRD §3.5: "the buyer must have enough available credit to cover the projected total
    due were this bid to win (otherwise `ERR_INSUFFICIENT_CREDIT`, HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_bid_to_non_open_lot_by_overcredit_buyer
    """
    admin = make_admin_headers()
    # With the lot actually BIDDING_OPEN, the state check passes and the fiscal check fires.
    ctx = setup_running_sale_with_lot(api, admin, reserve_price_cents=0, floor_price_cents=0,
                                      starting_bid_cents=400000)
    buyer = get_success_data(api.create_buyer(
        th.factories.create_buyer_payload(dealer_name="B1", credit_limit_cents=100), admin))
    lot_open = open_bidding(api, ctx["lot"]["id"], admin)
    resp = place_bid(api, ctx["lot"]["id"], buyer["id"], lot_open["version"],
                     bid_type="LIVE", amount_cents=400000, channel="LANE")
    validate_error(resp, "ERR_INSUFFICIENT_CREDIT")


def test_slot_overlap_fires_when_lane_reference_is_coherent(api):
    """PRD §3.4: "two slots that merely touch (the end of one equal to the start of the next,
    a gap of zero) do not overlap and are allowed, but any positive overlap is rejected with
    `ERR_LANE_SLOT_OVERLAP`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_lot_create_overlap_and_cross_sale_lane
    """
    admin = make_admin_headers()
    sale = get_success_data(api.create_sale(th.factories.create_sale_payload(), admin))
    lane = get_success_data(api.create_lane(th.factories.create_lane_payload(sale["id"]), admin))
    seller = get_success_data(api.create_seller(th.factories.create_seller_payload(), admin))
    cons1 = th.fixtures.make_cataloged_consignment(api, sale["id"], seller["id"], admin)
    cons2 = th.fixtures.make_cataloged_consignment(api, sale["id"], seller["id"], admin)
    th.fixtures.make_scheduled_lot(api, sale["id"], cons1["id"], lane["id"], admin,
                                   run_number=1, slot_start_minute=0, slot_end_minute=10)
    # Lane reference is coherent (same sale); only the temporal overlap fails -> ERR_LANE_SLOT_OVERLAP.
    resp = api.create_lot(
        th.factories.create_lot_payload(sale["id"], cons2["id"], lane["id"], run_number=2,
                                        slot_start_minute=5, slot_end_minute=15),
        admin,
    )
    validate_error(resp, "ERR_LANE_SLOT_OVERLAP")


# ─── boundary_precision_check (companions) ──────────────────────────────────
def test_bid_increment_band_just_below_500000_uses_10000(api):
    """PRD §3.5: "For a reference price below 500000 (under $5,000), the increment is 10000
    ($100)."

    Design: Difficulty/boundary_precision_check/bid_increment_band_boundary_at_exactly_500000
    """
    admin = make_admin_headers()
    # starting_bid 499999 (< 500000), B2 LIVE 499999, B1 PROXY 1000000.
    # second_ref = max(499999, 499999) = 499999; increment(499999) = 10000 (band1).
    # clearing = min(1000000, 499999 + 10000) = 509999.
    ctx = setup_running_sale_with_lot(api, admin, reserve_price_cents=0, floor_price_cents=0,
                                      starting_bid_cents=499999)
    b1 = get_success_data(api.create_buyer(th.factories.create_buyer_payload(dealer_name="B1"), admin))
    b2 = get_success_data(api.create_buyer(th.factories.create_buyer_payload(dealer_name="B2"), admin))
    lot_open = open_bidding(api, ctx["lot"]["id"], admin)
    place_bid_ok(api, ctx["lot"]["id"], b2["id"], lot_open["version"],
                 bid_type="LIVE", amount_cents=499999, channel="LANE")
    v1 = current_lot_version(api, ctx["lot"]["id"], admin)
    place_bid_ok(api, ctx["lot"]["id"], b1["id"], v1,
                 bid_type="PROXY", amount_cents=1000000, channel="ONLINE")
    lot = get_success_data(api.get_lot(ctx["lot"]["id"], admin))
    assert lot["high_bid_cents"] == 509999, lot


def test_reserve_threshold_below_reserve_yields_if_not_sold(api):
    """PRD §3.6: "the outcome to compute to `IF`, meaning `high_bidder_id` is not null but
    `high_bid_cents` is below the reserve (otherwise `ERR_OUTCOME_NOT_IF`)."
    PRD §3.6: "otherwise the outcome is `IF`."

    Design: Difficulty/boundary_precision_check/reserve_threshold_inclusive_sold_at_exact_reserve
    """
    admin = make_admin_headers()
    # Reserve 600001; single PROXY 600000, starting_bid 600000 -> clearing 600000 (< reserve) -> IF.
    ctx = setup_running_sale_with_lot(api, admin, reserve_price_cents=600001, floor_price_cents=0,
                                      starting_bid_cents=600000)
    buyer = get_success_data(api.create_buyer(th.factories.create_buyer_payload(dealer_name="B1"), admin))
    lot_open = open_bidding(api, ctx["lot"]["id"], admin)
    place_bid_ok(api, ctx["lot"]["id"], buyer["id"], lot_open["version"],
                 bid_type="PROXY", amount_cents=600000, channel="LANE")
    get_success_data(api.close_bidding(ctx["lot"]["id"], admin))
    # Hammer must be rejected because the outcome is IF, not SOLD.
    resp = api.hammer_lot(ctx["lot"]["id"], admin)
    validate_error(resp, "ERR_OUTCOME_NOT_SOLD")


# ─── resource_temporal_overlap (companions) ─────────────────────────────────
def test_lane_slot_adjacent_zero_gap_is_allowed(api):
    """PRD §3.4: "because intervals are half-open, two slots that merely touch (the end of
    one equal to the start of the next, a gap of zero) do not overlap and are allowed".

    Design: Difficulty/resource_temporal_overlap/lane_slot_half_open_overlap_rejected_adjacency_allowed
    """
    admin = make_admin_headers()
    sale = get_success_data(api.create_sale(th.factories.create_sale_payload(), admin))
    lane = get_success_data(api.create_lane(th.factories.create_lane_payload(sale["id"]), admin))
    seller = get_success_data(api.create_seller(th.factories.create_seller_payload(), admin))
    cons1 = th.fixtures.make_cataloged_consignment(api, sale["id"], seller["id"], admin)
    cons2 = th.fixtures.make_cataloged_consignment(api, sale["id"], seller["id"], admin)
    th.fixtures.make_scheduled_lot(api, sale["id"], cons1["id"], lane["id"], admin,
                                   run_number=1, slot_start_minute=0, slot_end_minute=10)
    # Adjacent [10,20) touches [0,10) at a single point -> allowed (gap == 0).
    resp = api.create_lot(
        th.factories.create_lot_payload(sale["id"], cons2["id"], lane["id"], run_number=2,
                                        slot_start_minute=10, slot_end_minute=20),
        admin,
    )
    created = th.validate_success(resp, 201)
    assert created["status"] == "SCHEDULED", created


def test_carrier_window_outside_buffer_is_allowed(api):
    """PRD §3.11: "the new window must keep a gap of at least the carrier's
    `turnaround_buffer_minutes` from every other non-`CANCELLED` transport order on the same
    carrier".

    Design: Difficulty/resource_temporal_overlap/carrier_buffered_closed_interval_conflict_rejected
    """
    admin = make_admin_headers()
    carrier = get_success_data(api.create_carrier(
        th.factories.create_carrier_payload(turnaround_buffer_minutes=30), admin))
    c1 = setup_cleared_settlement(api, admin, starting_bid_cents=400000, winning_amount_cents=800000,
                                  channel="LANE", credit_limit_cents=9_000_000)
    c2 = setup_cleared_settlement(api, admin, starting_bid_cents=400000, winning_amount_cents=800000,
                                  channel="LANE", credit_limit_cents=9_000_000)
    get_success_data(api.create_transport_order(
        th.factories.create_transport_order_payload(c1["settlement"]["id"], carrier["id"],
                                                    pickup_start_minute=600, pickup_end_minute=660),
        admin,
    ))
    # Second pickup [700,760]: gap from 660 is 40 >= 30 buffer -> allowed.
    resp = api.create_transport_order(
        th.factories.create_transport_order_payload(c2["settlement"]["id"], carrier["id"],
                                                    pickup_start_minute=700, pickup_end_minute=760),
        admin,
    )
    created = th.validate_success(resp, 201)
    assert created["status"] == "REQUESTED", created


# ─── compensating_invariant (companions) ────────────────────────────────────
def test_hammer_debits_buyer_credit_by_total_due(api):
    """PRD §2.10: "Striking a sale debits the winning buyer's available credit by exactly
    the lot's `total_due_cents`".

    Design: Difficulty/compensating_invariant/buyer_credit_conserved_across_hammer_and_arbitration_reversal
    """
    admin = make_admin_headers()
    ctx = setup_two_proxy_hammered_lot(
        api, admin, starting_bid_cents=600000, b1_ceiling=900000, b2_ceiling=700000,
        channel="ONLINE", buyer_fee_schedule_code="STANDARD", seller_fee_pct=0.02,
        b1_credit=2_000_000)
    b1 = get_success_data(api.get_buyer(ctx["b1"]["id"], admin))
    # Debited by total_due 772850 -> available 2,000,000 - 772850 = 1,227,150.
    assert b1["available_credit_cents"] == 1_227_150, b1


def test_lane_slot_count_increments_on_each_lot_create(api):
    """PRD §3.4: "creating a lot increments it by one, and the compensating withdraw or pass
    of a lot decrements it by one".

    Design: Difficulty/compensating_invariant/lane_slot_count_conserved_across_lot_create_and_withdraw
    """
    admin = make_admin_headers()
    sale = get_success_data(api.create_sale(th.factories.create_sale_payload(), admin))
    lane = get_success_data(api.create_lane(th.factories.create_lane_payload(sale["id"]), admin))
    seller = get_success_data(api.create_seller(th.factories.create_seller_payload(), admin))
    cons1 = th.fixtures.make_cataloged_consignment(api, sale["id"], seller["id"], admin)
    th.fixtures.make_scheduled_lot(api, sale["id"], cons1["id"], lane["id"], admin,
                                   run_number=1, slot_start_minute=0, slot_end_minute=10)
    lane_after_one = get_success_data(api.get_lane(lane["id"], admin))
    assert lane_after_one["scheduled_slot_count"] == 1, lane_after_one


# ─── optimistic_concurrency (companions) ────────────────────────────────────
def test_first_bid_with_open_version_is_accepted_and_recomputes_high_bidder(api):
    """PRD §3.5: "Each accepted bid is appended as an immutable, `PLACED` event whose
    read-only `ceiling_cents` is normalized to equal its `amount_cents`; the system then
    recomputes the lot's standing clearing price (updating `high_bid_cents` and
    `high_bidder_id`)".

    Design: Difficulty/optimistic_concurrency/stale_lot_version_on_second_bid_rejected_412
    """
    admin = make_admin_headers()
    ctx = setup_running_sale_with_lot(api, admin, reserve_price_cents=0, floor_price_cents=0,
                                      starting_bid_cents=400000)
    buyer = get_success_data(api.create_buyer(th.factories.create_buyer_payload(dealer_name="B1"), admin))
    lot_open = open_bidding(api, ctx["lot"]["id"], admin)
    place_bid_ok(api, ctx["lot"]["id"], buyer["id"], lot_open["version"],
                 bid_type="PROXY", amount_cents=500000, channel="LANE")
    lot = get_success_data(api.get_lot(ctx["lot"]["id"], admin))
    assert lot["high_bidder_id"] == buyer["id"], lot


def test_each_accepted_bid_increments_lot_version_by_one(api):
    """PRD §3.5: "the system then recomputes the lot's standing clearing price (updating
    `high_bid_cents` and `high_bidder_id`) and increments the lot's `version` by one."

    Design: Difficulty/optimistic_concurrency/fresh_lot_version_on_second_bid_succeeds_and_bumps_version
    """
    admin = make_admin_headers()
    ctx = setup_running_sale_with_lot(api, admin, reserve_price_cents=0, floor_price_cents=0,
                                      starting_bid_cents=400000)
    buyer = get_success_data(api.create_buyer(th.factories.create_buyer_payload(dealer_name="B1"), admin))
    lot_open = open_bidding(api, ctx["lot"]["id"], admin)
    v0 = lot_open["version"]
    place_bid_ok(api, ctx["lot"]["id"], buyer["id"], v0,
                 bid_type="PROXY", amount_cents=500000, channel="LANE")
    lot = get_success_data(api.get_lot(ctx["lot"]["id"], admin))
    assert lot["version"] == v0 + 1, lot
