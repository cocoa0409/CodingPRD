"""Entity lifecycles, cyclic state machines, and cross-entity cascades.

Covers the unit sale/repossession cycle, the work-order parts loop, the depth-3
fund and unwind cascades, auction settlement side effects, and whole-goods
fulfillment.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_paginated, get_success_data,
    create_unit_payload, create_customer_payload, create_floor_plan_note_payload,
    create_deal_payload, create_trade_in_payload, create_work_order_payload,
    create_part_payload, create_part_line_payload, create_whole_goods_order_payload,
    create_customer, create_unit, create_part, create_offered_trade_in,
    create_approved_deal, fund_deal, get_unit_version, create_active_floor_plan_note,
    create_funded_sale_deal, create_funded_sale_with_trade,
    create_in_progress_work_order, add_part_line,
    create_closed_no_sale_lot, create_closed_met_lot, create_confirmed_order,
    setup_unit_with_active_floor_plan,
    TEST_USERS,
)

ADMIN = TEST_USERS["dealer_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]
SERVICE = TEST_USERS["service_advisor_headers"]
PARTS = TEST_USERS["parts_clerk_headers"]
AUCTION = TEST_USERS["auction_clerk_headers"]


# ─── Unit cyclic: SOLD -> REPOSSESSED -> AVAILABLE (Difficulty/non_linear_state_machine) ──

def test_unit_unwind_then_recondition_returns_to_available(api):
    """PRD §3.1: "a funded sale that is later unwound moves the unit
    `SOLD → REPOSSESSED`, and a `DealerAdmin` reconditioning capability returns it
    `REPOSSESSED → AVAILABLE`, completing the cycle
    `AVAILABLE → SOLD → REPOSSESSED → AVAILABLE`."

    Design: Difficulty/non_linear_state_machine/unit_cyclic_sold_repossessed_available
    """
    unit, _, deal = create_funded_sale_deal(
        sale_price_cents=6000000,
        customer_overrides={"name": "Repo Buyer", "customer_type": "RETAIL"},
        unit_overrides={"condition": "USED", "engine_hours": 300},
    )
    v_now = get_unit_version(unit["id"])
    unwound = validate_success(
        api.unwind_deal(deal["id"], {"expected_unit_version": v_now}, FINANCE), 200)
    assert unwound["status"] == "UNWOUND"
    reconditioned = validate_success(api.recondition_unit(unit["id"], ADMIN), 200)
    assert reconditioned["status"] == "AVAILABLE"


def test_unit_unwind_moves_to_repossessed(api):
    """PRD §3.4: "it reverses `tax_cents` and `trade_allowance_cents` back to 0,
    moves the unit `SOLD → REPOSSESSED` as a cascade".

    Design: Difficulty/non_linear_state_machine/unit_cyclic_sold_repossessed_available
    """
    unit, _, deal = create_funded_sale_deal(
        sale_price_cents=6000000,
        customer_overrides={"name": "Repo Two", "customer_type": "RETAIL"},
        unit_overrides={"condition": "USED", "engine_hours": 300},
    )
    v_now = get_unit_version(unit["id"])
    validate_success(api.unwind_deal(deal["id"], {"expected_unit_version": v_now}, FINANCE), 200)
    unit_after = validate_success(api.get_unit(unit["id"], FINANCE), 200)
    assert unit_after["status"] == "REPOSSESSED"


# ─── Work-order parts loop (Difficulty/non_linear_state_machine) ─────────────

def test_work_order_resume_returns_to_in_progress(api):
    """PRD §3.6: "When parts arrive, the advisor resumes the order, moving it
    `AWAITING_PARTS → IN_PROGRESS` (the order may cycle between these two states)."

    Design: Difficulty/non_linear_state_machine/work_order_cyclic_in_progress_awaiting_parts_loop
    """
    _, _, wo, _, _ = create_in_progress_work_order(
        wo_overrides={"labor_rate_cents": 14000, "flat_rate_hours": 2.0},
        part_qty=3, part_overrides={"sku": "FLT-001", "category": "FILTER",
                                    "unit_price_cents": 8000, "on_hand_qty": 1},
    )
    held = validate_success(api.hold_work_order(wo["id"], SERVICE), 200)
    assert held["status"] == "AWAITING_PARTS"
    resumed = validate_success(api.resume_work_order(wo["id"], SERVICE), 200)
    assert resumed["status"] == "IN_PROGRESS"


def test_work_order_hold_for_parts_enters_awaiting(api):
    """PRD §3.6: "When a needed part is short, the advisor holds the order for
    parts, moving it `IN_PROGRESS → AWAITING_PARTS`; this hold is permitted only
    when at least one part line on the order references a part whose available
    quantity (its `on_hand_qty` minus its `reserved_qty`) is less than that line's
    `quantity`."

    Design: Difficulty/non_linear_state_machine/work_order_cyclic_in_progress_awaiting_parts_loop
    """
    _, _, wo, _, _ = create_in_progress_work_order(
        wo_overrides={"labor_rate_cents": 14000, "flat_rate_hours": 2.0},
        part_qty=3, part_overrides={"sku": "FLT-LOOP", "category": "FILTER",
                                    "unit_price_cents": 8000, "on_hand_qty": 1},
    )
    held = validate_success(api.hold_work_order(wo["id"], SERVICE), 200)
    assert held["status"] == "AWAITING_PARTS"


# ─── Depth-3 fund cascade (Difficulty/transitive_cascade) ────────────────────

def test_fund_cascades_floorplan_payoff(api):
    """PRD §3.4: "If the unit is floor-planned, the `ACTIVE` or `CURTAILMENT_DUE`
    floor-plan note is paid off as a cascade (note `→ PAID_OFF`,
    `floor_planned → false`)."

    Design: Difficulty/transitive_cascade/deal_fund_cascade_floorplan_payoff_depth3
    """
    unit = create_unit(condition="NEW", model_code="7R290", dealer_cost_cents=7000000,
                       list_price_cents=9000000)
    note = create_active_floor_plan_note(unit["id"], principal_cents=7000000, annual_rate_bps=800)
    customer = create_customer(name="FP Buyer", customer_type="RETAIL")
    deal = get_success_data(api.create_deal(create_deal_payload(
        unit["id"], customer["id"], deal_type="SALE", sale_price_cents=9000000), SALES))
    get_success_data(api.approve_deal(deal["id"], FINANCE))
    funded = fund_deal(deal["id"], unit["id"])
    assert funded["status"] == "FUNDED"
    unit_after = validate_success(api.get_unit(unit["id"], FINANCE), 200)
    assert unit_after["status"] == "SOLD"
    assert unit_after["floor_planned"] is False
    note_after = validate_success(api.get_floor_plan_note(note["id"], FINANCE), 200)
    assert note_after["status"] == "PAID_OFF"


def test_fund_floorplanned_unit_clears_floor_planned_flag(api):
    """PRD §3.2: "A floor-plan note is paid off as a cascade, never directly: when
    the financed unit is sold, leased, or sold at auction, an `ACTIVE` or
    `CURTAILMENT_DUE` note on that unit moves to `PAID_OFF` (terminal), its
    `interest_accrued_cents` is frozen at its final value, and the unit's
    `floor_planned` flag clears to `false`."

    Design: Difficulty/transitive_cascade/deal_fund_cascade_floorplan_payoff_depth3
    """
    unit, note = setup_unit_with_active_floor_plan(
        unit_overrides={"condition": "NEW", "dealer_cost_cents": 7000000, "list_price_cents": 9000000},
        note_overrides={"principal_cents": 7000000, "annual_rate_bps": 800},
    )
    before = validate_success(api.get_unit(unit["id"], FINANCE), 200)
    assert before["floor_planned"] is True
    customer = create_customer(name="FP Buyer 2", customer_type="RETAIL")
    deal = get_success_data(api.create_deal(create_deal_payload(
        unit["id"], customer["id"], deal_type="SALE", sale_price_cents=9000000), SALES))
    get_success_data(api.approve_deal(deal["id"], FINANCE))
    fund_deal(deal["id"], unit["id"])
    note_after = validate_success(api.get_floor_plan_note(note["id"], FINANCE), 200)
    assert note_after["status"] == "PAID_OFF"


# ─── Depth-3 unwind cascade (Difficulty/transitive_cascade) ──────────────────

def test_unwind_cascades_repossess_and_trade_revert(api):
    """PRD §3.4: "Unwinding moves the deal `FUNDED → UNWOUND` (terminal) ... it
    reverses `tax_cents` and `trade_allowance_cents` back to 0, moves the unit
    `SOLD → REPOSSESSED` as a cascade, and, if the deal had a trade-in, retires the
    minted unit and reverts that trade `ACCEPTED → DECLINED`."

    Design: Difficulty/transitive_cascade/deal_unwind_cascade_unit_repossess_tradein_revert_depth3
    """
    unit, _, deal, _, minted_unit_id = create_funded_sale_with_trade(
        sale_price_cents=8000000,
        trade_overrides={"model_code": "8295R", "engine_hours": 800,
                         "condition_grade": "FAIR", "base_value_cents": 5000000},
    )
    v_now = get_unit_version(unit["id"])
    unwound = validate_success(
        api.unwind_deal(deal["id"], {"expected_unit_version": v_now}, FINANCE), 200)
    assert unwound["status"] == "UNWOUND"
    unit_after = validate_success(api.get_unit(unit["id"], FINANCE), 200)
    assert unit_after["status"] == "REPOSSESSED"
    minted_after = validate_success(api.get_unit(minted_unit_id, FINANCE), 200)
    assert minted_after["status"] == "RETIRED"


def test_unwind_reverts_trade_to_declined(api):
    """PRD §3.3: "Should that funding deal later be unwound, the trade is reverted
    `ACCEPTED → DECLINED` and the minted unit is retired, again as a cascade."

    Design: Difficulty/transitive_cascade/deal_unwind_cascade_unit_repossess_tradein_revert_depth3
    """
    unit, _, deal, trade, _ = create_funded_sale_with_trade(
        sale_price_cents=8000000,
        trade_overrides={"model_code": "8295R", "engine_hours": 800,
                         "condition_grade": "FAIR", "base_value_cents": 5000000},
    )
    assert trade["status"] == "ACCEPTED"
    v_now = get_unit_version(unit["id"])
    validate_success(api.unwind_deal(deal["id"], {"expected_unit_version": v_now}, FINANCE), 200)
    trade_after = validate_success(api.get_trade_in(trade["id"], FINANCE), 200)
    assert trade_after["status"] == "DECLINED"


# ─── Compensating invariant: unwind restores inventory (Difficulty/compensating_invariant) ──

def test_unwind_restores_non_retired_unit_count(api):
    """PRD §3.4: "Unwinding moves the deal `FUNDED → UNWOUND` (terminal) and is a
    compensating action whose net effect must return the dealer's cash position to
    its pre-funding value".

    Design: Difficulty/compensating_invariant/deal_unwind_restores_unit_inventory_count
    """
    unit, _, deal, trade, minted_unit_id = create_funded_sale_with_trade(
        sale_price_cents=8000000,
        trade_overrides={"model_code": "7830", "engine_hours": 800,
                         "condition_grade": "FAIR", "base_value_cents": 5000000},
    )
    # Before unwind, two non-retired units traceable to the deal exist (original SOLD + minted).
    v_now = get_unit_version(unit["id"])
    validate_success(api.unwind_deal(deal["id"], {"expected_unit_version": v_now}, FINANCE), 200)
    original = validate_success(api.get_unit(unit["id"], FINANCE), 200)
    minted = validate_success(api.get_unit(minted_unit_id, FINANCE), 200)
    trade_after = validate_success(api.get_trade_in(trade["id"], FINANCE), 200)
    assert original["status"] == "REPOSSESSED"
    assert minted["status"] == "RETIRED"
    assert trade_after["status"] == "DECLINED"
    # Conserved non_retired_unit_count of {original, minted} == 1 (only original remains).
    non_retired = sum(1 for u in (original, minted) if u["status"] != "RETIRED")
    assert non_retired == 1


def test_unwind_reverses_tax_and_trade_allowance(api):
    """PRD §3.4: "it reverses `tax_cents` and `trade_allowance_cents` back to 0".

    Design: Difficulty/compensating_invariant/deal_unwind_restores_unit_inventory_count
    """
    unit, _, deal, _, _ = create_funded_sale_with_trade(
        sale_price_cents=8000000,
        trade_overrides={"model_code": "7830B", "engine_hours": 800,
                         "condition_grade": "FAIR", "base_value_cents": 5000000},
    )
    assert deal["trade_allowance_cents"] > 0
    v_now = get_unit_version(unit["id"])
    unwound = validate_success(
        api.unwind_deal(deal["id"], {"expected_unit_version": v_now}, FINANCE), 200)
    assert unwound["tax_cents"] == 0
    assert unwound["trade_allowance_cents"] == 0


# ─── Compensating invariant: void restores reserved qty (Difficulty/compensating_invariant) ──

def test_void_work_order_restores_reserved_qty(api):
    """PRD §3.6: "Finally, a service advisor may void an open work order, moving it
    `OPEN → VOID` (terminal); voiding releases any reserved parts back to
    availability and posts no charges."

    Design: Difficulty/compensating_invariant/work_order_void_restores_part_reserved_quantity
    """
    customer = create_customer(name="WV Cust", customer_type="RETAIL")
    unit = create_unit(condition="USED", model_code="5090E", engine_hours=1200)
    part = create_part(sku="OIL-22", description="oil filter", category="FILTER",
                       unit_price_cents=3000, on_hand_qty=10)
    wo = get_success_data(api.create_work_order(create_work_order_payload(
        unit["id"], customer["id"], complaint="service", labor_rate_cents=12000,
        flat_rate_hours=1.0), SERVICE))
    add_part_line(wo["id"], part["id"], 4)
    reserved_before = validate_success(api.get_part(part["id"], PARTS), 200)["reserved_qty"]
    assert reserved_before == 4
    voided = validate_success(api.void_work_order(wo["id"], SERVICE), 200)
    assert voided["status"] == "VOID"
    part_after = validate_success(api.get_part(part["id"], PARTS), 200)
    assert part_after["reserved_qty"] == 0
    assert part_after["on_hand_qty"] == 10


def test_void_work_order_posts_no_charges_and_releases_stock(api):
    """PRD §3.6: "A part also carries a computed `reserved_qty`: the sum of the
    `quantity` of every part line that references the part and whose owning work
    order is `OPEN`, `IN_PROGRESS`, or `AWAITING_PARTS`."

    Design: Difficulty/compensating_invariant/work_order_void_restores_part_reserved_quantity
    """
    customer = create_customer(name="WV2 Cust", customer_type="RETAIL")
    unit = create_unit(condition="USED", model_code="5090E", engine_hours=1200)
    part = create_part(sku="OIL-23", description="oil filter", category="FILTER",
                       unit_price_cents=3000, on_hand_qty=10)
    wo = get_success_data(api.create_work_order(create_work_order_payload(
        unit["id"], customer["id"], complaint="service", labor_rate_cents=12000,
        flat_rate_hours=1.0), SERVICE))
    add_part_line(wo["id"], part["id"], 4)
    validate_success(api.void_work_order(wo["id"], SERVICE), 200)
    # Once the owning WO is VOID, the part line no longer reserves stock.
    part_after = validate_success(api.get_part(part["id"], PARTS), 200)
    assert part_after["reserved_qty"] == 0


# ─── Auction settlement side effects (Corner/state_machines) ─────────────────

def test_auction_close_no_sale_releases_unit_to_available(api):
    """PRD §3.5: "Settling a `CLOSED_NO_SALE` lot moves it `CLOSED_NO_SALE →
    SETTLED` with no deal created, releasing the unit `AUCTION_LISTED → AVAILABLE`
    as a cascade and incrementing the unit's `version` by one."

    Design: Corner/state_machines/auction_close_no_sale_releases_unit_to_available
    """
    unit, lot = create_closed_no_sale_lot(reserve_price_cents=4500000)
    v_now = get_unit_version(unit["id"])
    settled = validate_success(
        api.settle_auction_lot(lot["id"], {"expected_unit_version": v_now}, AUCTION), 200)
    assert settled["status"] == "SETTLED"
    unit_after = validate_success(api.get_unit(unit["id"], AUCTION), 200)
    assert unit_after["status"] == "AVAILABLE"


def test_auction_settle_met_creates_funded_auction_sale_deal(api):
    """PRD §3.5: "Settling a `CLOSED_MET` lot moves it `CLOSED_MET → SETTLED`
    (terminal): it creates an `AUCTION_SALE` deal in `FUNDED` status for the high
    bidder at the `high_bid_cents`, moves the unit `AUCTION_LISTED → AUCTION_SOLD`,
    ... sets the lot's `winning_deal_id` to the created deal".

    Design: Corner/state_machines/auction_settle_met_creates_funded_auction_sale_deal
    """
    unit, lot, _ = create_closed_met_lot(reserve_price_cents=4000000, bid_amount_cents=4800000)
    v_now = get_unit_version(unit["id"])
    settled = validate_success(
        api.settle_auction_lot(lot["id"], {"expected_unit_version": v_now}, AUCTION), 200)
    assert settled["status"] == "SETTLED"
    unit_after = validate_success(api.get_unit(unit["id"], AUCTION), 200)
    assert unit_after["status"] == "AUCTION_SOLD"
    deal = validate_success(api.get_deal(settled["winning_deal_id"], AUCTION), 200)
    assert deal["status"] == "FUNDED"
    assert deal["deal_type"] == "AUCTION_SALE"
    assert deal["sale_price_cents"] == 4800000


# ─── Whole-goods fulfillment (Corner/state_machines) ─────────────────────────

def test_whole_goods_two_step_partial_then_full_fulfillment(api):
    """PRD §3.8: "when an allocation brings `fulfilled_qty` up to `quantity`, the
    order moves to `FULFILLED` (terminal) — either `PARTIAL_FULFILLED → FULFILLED`,
    or directly `CONFIRMED → FULFILLED` when the order quantity is exactly 1 and is
    filled in a single step."

    Design: Corner/state_machines/whole_goods_two_step_partial_then_full_fulfillment
    """
    customer, order = create_confirmed_order(
        customer_overrides={"name": "WG Cust", "customer_type": "COMMERCIAL_AG"},
        order_overrides={"model_code": "5075E", "season_program": "EARLY_ORDER",
                         "quantity": 2, "unit_msrp_cents": 5000000},
    )
    u1 = create_unit(condition="NEW", model_code="5075E", dealer_cost_cents=3800000,
                     list_price_cents=5000000)
    u2 = create_unit(condition="NEW", model_code="5075E", dealer_cost_cents=3800000,
                     list_price_cents=5000000)
    after1 = validate_success(
        api.allocate_whole_goods_order(order["id"], {"unit_id": u1["id"]}, SALES), 200)
    assert after1["status"] == "PARTIAL_FULFILLED"
    assert after1["fulfilled_qty"] == 1
    after2 = validate_success(
        api.allocate_whole_goods_order(order["id"], {"unit_id": u2["id"]}, SALES), 200)
    assert after2["status"] == "FULFILLED"
    assert after2["fulfilled_qty"] == 2
    assert validate_success(api.get_unit(u1["id"], SALES), 200)["status"] == "RESERVED"
    assert validate_success(api.get_unit(u2["id"], SALES), 200)["status"] == "RESERVED"
