"""Optimistic concurrency on the live block, half-open lane-slot and buffered carrier
window overlap rules, and validation-precedence pairs where one check pre-empts another.
"""
import pytest

from test_helpers import (
    make_admin_headers, make_buyer_headers,
    get_success_data, validate_error,
    setup_running_sale_with_lot, setup_cleared_settlement,
    open_bidding, current_lot_version, place_bid, place_bid_ok, get_settlement_for_lot,
)
import test_helpers as th


# ─── optimistic_concurrency ─────────────────────────────────────────────────
def test_stale_lot_version_on_second_bid_rejected_412(api):
    """PRD §2.9: "If `expected_lot_version` does not equal the lot's current `version` —
    because another bid was appended after the client read the lot, legitimately advancing
    the standing clearing price and the lot's version — the placement is rejected with
    `ERR_STALE_LOT_VERSION` (HTTP 412)."

    Design: Difficulty/optimistic_concurrency/stale_lot_version_on_second_bid_rejected_412
    """
    admin = make_admin_headers()
    ctx = setup_running_sale_with_lot(api, admin, reserve_price_cents=0, floor_price_cents=0,
                                      starting_bid_cents=400000)
    b1 = get_success_data(api.create_buyer(th.factories.create_buyer_payload(dealer_name="B1"), admin))
    b2 = get_success_data(api.create_buyer(th.factories.create_buyer_payload(dealer_name="B2"), admin))
    lot_open = open_bidding(api, ctx["lot"]["id"], admin)
    v0 = lot_open["version"]
    # B1's accepted bid advances the lot version past v0.
    place_bid_ok(api, ctx["lot"]["id"], b1["id"], v0, bid_type="PROXY", amount_cents=500000, channel="LANE")
    # B2 still carries the stale v0 -> 412.
    resp = place_bid(api, ctx["lot"]["id"], b2["id"], v0, bid_type="LIVE", amount_cents=520000, channel="LANE")
    validate_error(resp, "ERR_STALE_LOT_VERSION")


def test_fresh_lot_version_on_second_bid_succeeds_and_bumps_version(api):
    """PRD §2.9: "A bid-placement request must include `expected_lot_version`, carrying the
    `version` of the lot (the `RunListEntry`) that the client last observed."
    PRD §3.5: "the system then recomputes the lot's standing clearing price (updating
    `high_bid_cents` and `high_bidder_id`) and increments the lot's `version` by one."

    Design: Difficulty/optimistic_concurrency/fresh_lot_version_on_second_bid_succeeds_and_bumps_version
    """
    admin = make_admin_headers()
    ctx = setup_running_sale_with_lot(api, admin, reserve_price_cents=0, floor_price_cents=0,
                                      starting_bid_cents=400000)
    b1 = get_success_data(api.create_buyer(th.factories.create_buyer_payload(dealer_name="B1"), admin))
    b2 = get_success_data(api.create_buyer(th.factories.create_buyer_payload(dealer_name="B2"), admin))
    lot_open = open_bidding(api, ctx["lot"]["id"], admin)
    place_bid_ok(api, ctx["lot"]["id"], b1["id"], lot_open["version"],
                 bid_type="PROXY", amount_cents=500000, channel="LANE")
    v1 = current_lot_version(api, ctx["lot"]["id"], admin)
    # B2 carries the fresh v1 -> accepted; version increments to v1+1.
    place_bid_ok(api, ctx["lot"]["id"], b2["id"], v1,
                 bid_type="PROXY", amount_cents=900000, channel="ONLINE")
    lot = get_success_data(api.get_lot(ctx["lot"]["id"], admin))
    assert lot["high_bidder_id"] == b2["id"], lot
    assert lot["version"] == v1 + 1, lot


# ─── resource_temporal_overlap ──────────────────────────────────────────────
def test_lane_slot_half_open_overlap_rejected(api):
    """PRD §3.4: "it must not overlap the slot of any other lot in the same lane that is not
    `WITHDRAWN` or `PASSED`; because intervals are half-open, two slots that merely touch
    (the end of one equal to the start of the next, a gap of zero) do not overlap and are
    allowed, but any positive overlap is rejected with `ERR_LANE_SLOT_OVERLAP`."

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
    # New lot [5,15) overlaps existing [0,10) -> ERR_LANE_SLOT_OVERLAP.
    resp = api.create_lot(
        th.factories.create_lot_payload(sale["id"], cons2["id"], lane["id"], run_number=2,
                                        slot_start_minute=5, slot_end_minute=15),
        admin,
    )
    validate_error(resp, "ERR_LANE_SLOT_OVERLAP")


def test_carrier_buffered_closed_interval_conflict_rejected(api):
    """PRD §3.11: "treating each pickup window as a closed interval, the new window must keep
    a gap of at least the carrier's `turnaround_buffer_minutes` from every other
    non-`CANCELLED` transport order on the same carrier; a window that does not preserve that
    buffered closed-interval separation is rejected with `ERR_CARRIER_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/carrier_buffered_closed_interval_conflict_rejected
    """
    admin = make_admin_headers()
    carrier = get_success_data(api.create_carrier(
        th.factories.create_carrier_payload(turnaround_buffer_minutes=30), admin))
    c1 = setup_cleared_settlement(api, admin, starting_bid_cents=400000, winning_amount_cents=800000,
                                  channel="LANE", credit_limit_cents=9_000_000)
    c2 = setup_cleared_settlement(api, admin, starting_bid_cents=400000, winning_amount_cents=800000,
                                  channel="LANE", credit_limit_cents=9_000_000)
    # First pickup [600,660]; second [665,725] -> only 5 min gap < 30 buffer -> conflict.
    get_success_data(api.create_transport_order(
        th.factories.create_transport_order_payload(c1["settlement"]["id"], carrier["id"],
                                                    pickup_start_minute=600, pickup_end_minute=660),
        admin,
    ))
    resp = api.create_transport_order(
        th.factories.create_transport_order_payload(c2["settlement"]["id"], carrier["id"],
                                                    pickup_start_minute=665, pickup_end_minute=725),
        admin,
    )
    validate_error(resp, "ERR_CARRIER_WINDOW_CONFLICT")


# ─── priority_pair_validation_conflict ──────────────────────────────────────
def test_state_check_pre_empts_credit_check_on_bid_to_scheduled_lot(api):
    """PRD §2.6: "fifth, the target resource's state precondition for the requested
    transition (the transition's specific state error, all HTTP 409); ... and finally the
    remaining business-constraint, fiscal, and concurrency checks."
    PRD §3.5: "the lot must be `BIDDING_OPEN` (otherwise `ERR_LOT_NOT_BIDDING_OPEN`)".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_bid_to_non_open_lot_by_overcredit_buyer
    """
    admin = make_admin_headers()
    # Lot left SCHEDULED (bidding never opened); buyer credit_limit 100 (far below any total_due).
    ctx = setup_running_sale_with_lot(api, admin, reserve_price_cents=0, floor_price_cents=0,
                                      starting_bid_cents=400000)
    buyer = get_success_data(api.create_buyer(
        th.factories.create_buyer_payload(dealer_name="B1", credit_limit_cents=100), admin))
    lot = get_success_data(api.get_lot(ctx["lot"]["id"], admin))
    resp = api.place_bid(
        ctx["lot"]["id"],
        th.factories.place_bid_payload(buyer["id"], lot["version"], bid_type="LIVE",
                                       amount_cents=400000, channel="LANE"),
        make_buyer_headers(buyer["id"]),
    )
    # State check (lot not BIDDING_OPEN) wins over the credit check.
    validate_error(resp, "ERR_LOT_NOT_BIDDING_OPEN")


def test_cross_sale_reference_pre_empts_slot_overlap_on_lot_create(api):
    """PRD §2.6: "sixth, cross-reference coherence between aggregates
    (`ERR_CROSS_SALE_REFERENCE`); seventh, temporal-window rules for lane slots and carrier
    pickups".
    PRD §3.4: "Cross-aggregate coherence comes first: the lot's `lane_id` and
    `consignment_id` must both belong to the same sale as the lot's `sale_id`; a reference
    that crosses sales is rejected with `ERR_CROSS_SALE_REFERENCE`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_lot_create_overlap_and_cross_sale_lane
    """
    admin = make_admin_headers()
    sale_a = get_success_data(api.create_sale(th.factories.create_sale_payload(sale_name="A"), admin))
    sale_b = get_success_data(api.create_sale(
        th.factories.create_sale_payload(sale_name="B", sale_date="2026-06-03T09:00:00Z"), admin))
    lane_a = get_success_data(api.create_lane(th.factories.create_lane_payload(sale_a["id"]), admin))
    lane_b = get_success_data(api.create_lane(th.factories.create_lane_payload(sale_b["id"]), admin))
    seller = get_success_data(api.create_seller(th.factories.create_seller_payload(), admin))
    cons1 = th.fixtures.make_cataloged_consignment(api, sale_a["id"], seller["id"], admin)
    cons2 = th.fixtures.make_cataloged_consignment(api, sale_a["id"], seller["id"], admin)
    # Existing lot in sale A lane A at [0,10).
    th.fixtures.make_scheduled_lot(api, sale_a["id"], cons1["id"], lane_a["id"], admin,
                                   run_number=1, slot_start_minute=0, slot_end_minute=10)
    # New lot in sale A but lane_id = lane_b (cross-sale) AND slot [0,5) overlaps -> referential wins.
    resp = api.create_lot(
        th.factories.create_lot_payload(sale_a["id"], cons2["id"], lane_b["id"], run_number=1,
                                        slot_start_minute=0, slot_end_minute=5),
        admin,
    )
    validate_error(resp, "ERR_CROSS_SALE_REFERENCE")
