"""Second test per difficulty instance: the complementary / boundary-passing case
that, together with its sibling in test_01–test_05, pins the rule from both sides.
Each test carries the same Design tag as its sibling.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    create_customer, create_inventory_item, create_inventory_item_with_stock,
    create_submitted_buylist, create_listed_consignment,
    create_open_event, create_registration, create_paid_registration,
    create_release_product, create_requested_pre_order, create_allocated_pre_order,
    setup_in_progress_event_with_two_players, create_pairing, report_pairing,
    create_event, set_clock,
    ApiErrorId, TEST_USERS, make_customer_headers,
)

SM = TEST_USERS["store_manager_headers"]
JUDGE = TEST_USERS["judge_headers"]


# ─── dual_variant_calc / registration_provisional_vs_final_fee (2nd) ────────────
def test_silver_provisional_fee_applies_loyalty_only(api):
    """PRD §3.4: "0 basis points for `BRONZE`, 500 (5%) for `SILVER`, and 1000 (10%)
    for `GOLD`, where a basis-point figure is converted to a fraction by dividing by
    10000. The provisional variant, computed at registration before the early-bird
    window is known, applies only the loyalty discount: the quoted fee is the base
    multiplied by one minus the loyalty fraction, rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/registration_provisional_vs_final_fee
    """
    set_clock("2026-06-01T00:00:00Z")
    # Reach SILVER: pay a 50000 fee so lifetime_spend hits 50000 (>= threshold).
    cust = create_customer("Silver Cust", "silverfee@x.com", credit_cents=120000)
    pricey = create_open_event(title="Pricey", format="STANDARD",
                               starts_at="2026-06-20T00:00:00Z",
                               ends_at="2026-06-20T04:00:00Z", capacity=8,
                               entry_fee_cents=50000)
    create_paid_registration(pricey, cust)  # lifetime_spend 50000 -> SILVER
    cust_silver = validate_success(api.get_customer(cust["id"], SM), 200)
    assert cust_silver["loyalty_tier"] == "SILVER"
    # New SILVER registration: provisional fee = 2000 * (1 - 0.05) = 1900
    ev2 = create_open_event(title="Silver FNM", format="MODERN",
                            starts_at="2026-06-30T00:00:00Z",
                            ends_at="2026-06-30T04:00:00Z", capacity=8,
                            entry_fee_cents=2000)
    reg = create_registration(ev2, cust)
    assert reg["quoted_fee_cents"] == 1900


# ─── combinatorial_formula / preorder_priority_three_input_nonlinear (2nd) ──────
def test_preorder_priority_deposit_points_capped_at_thirty(api):
    """PRD §3.3: "The second is a deposit component: the deposit paid is divided by
    500 cents, the quotient is taken as a whole number (discarding any remainder),
    and that count of points is capped at a maximum of 30."
    PRD §3.3: "the component is 25 minus 5 for each rank position past the first —
    that is, 25 for rank 1, 20 for rank 2, and so on — but never less than 0."

    Design: Difficulty/combinatorial_formula/preorder_priority_three_input_nonlinear
    """
    cust = create_customer("Big Deposit", "bigdep@x.com", credit_cents=50000)
    rp = create_release_product(title="Cap Box", allocation_pool=100,
                                unit_price_cents=9000, deposit_required_cents=1000)
    # deposit 20000 -> 20000//500 = 40, capped to 30; rank 1 recency 25; tier 0 -> 55
    po = create_requested_pre_order(cust, rp, requested_quantity=1,
                                    deposit_paid_cents=20000)
    assert po["priority_score"] == 55


# ─── combinatorial_formula / consignment_round_per_unit_then_multiply (2nd) ─────
def test_consignment_payout_no_commission_full_ask(api):
    """PRD §3.7: "the per-unit commission is the `ask_price_cents` multiplied by the
    `commission_rate_bps` divided by 10000, rounded half-up to whole cents; the
    per-unit net is the ask price minus that per-unit commission; and
    `payout_total_cents` is the per-unit net multiplied by the case `quantity`."

    Design: Difficulty/combinatorial_formula/consignment_round_per_unit_then_multiply
    """
    cust = create_customer("Zero Comm", "zerocomm@x.com")
    item = create_inventory_item(title="Premium Single", market_price_cents=10000)
    cc = create_listed_consignment(cust, item, quantity=4, ask_price_cents=10000,
                                   commission_rate_bps=0)
    sold = validate_success(api.sell_consignment_case(cc["id"], SM), 200)
    # commission 0; net 10000; total 10000*4 = 40000
    assert sold["payout_total_cents"] == 40000


# ─── non_linear_state_machine / event_cyclic_round_advance (2nd) ────────────────
def test_event_advance_round_twice_reaches_round_three(api):
    """PRD §3.5: "Advancing to the next round is a judge-staff action and a cyclic
    self-transition: it keeps the event `IN_PROGRESS` while incrementing
    `current_round` by one, opening a new round for pairing."

    Design: Difficulty/non_linear_state_machine/event_cyclic_round_advance
    """
    ev, ca, cb, ra, rb = setup_in_progress_event_with_two_players(
        starts_at="2026-08-01T00:00:00Z", ends_at="2026-08-01T05:00:00Z")
    pr1 = create_pairing(ev, ra, rb)
    report_pairing(pr1, "A_WINS")
    r2 = validate_success(api.advance_round(ev["id"], JUDGE), 200)
    assert r2["current_round"] == 2
    # Round 2: another pairing, report, advance again -> round 3 (cycle repeats).
    pr2 = create_pairing(r2, ra, rb)
    report_pairing(pr2, "B_WINS")
    r3 = validate_success(api.advance_round(ev["id"], JUDGE), 200)
    assert r3["current_round"] == 3
    assert r3["status"] == "IN_PROGRESS"


# ─── transitive_cascade / event_cancel_refund_ledger_depth3 (2nd) ───────────────
def test_event_cancel_appends_event_refund_ledger_row(api):
    """PRD §3.5: "any such registration whose `payment_status` is `PAID` is driven to
    `REFUNDED`, which in turn appends an `EVENT_REFUND` ledger row and recomputes that
    customer's `store_credit_balance_cents`."

    Design: Difficulty/transitive_cascade/event_cancel_refund_ledger_depth3
    """
    set_clock("2026-06-01T00:00:00Z")
    cust = create_customer("Ledger Cancel", "ledgcancel@x.com", credit_cents=5000)
    ev = create_open_event(title="Ledger Doomed", format="STANDARD",
                           starts_at="2026-06-10T00:00:00Z",
                           ends_at="2026-06-10T04:00:00Z", capacity=8,
                           entry_fee_cents=2000)
    create_paid_registration(ev, cust)
    validate_success(api.cancel_event(ev["id"], SM), 200)
    rows, _ = validate_paginated(api.list_ledger(cust["id"], SM))
    reasons = [r["reason"] for r in rows]
    assert "EVENT_REFUND" in reasons, f"expected an EVENT_REFUND row, got {reasons}"


# ─── transitive_cascade / buylist_accept_inventory_and_credit_depth2 (2nd) ──────
def test_buylist_accept_pins_line_payout(api):
    """PRD §3.2: "the result is rounded half-up to a whole number of cents and pinned
    as that line's `line_payout_cents`. The submission's `offered_total_cents` is
    then the sum of the pinned per-line payouts."
    PRD §3.2: "acceptance adds each accepted line's quantity to the mapped inventory
    item's `quantity_on_hand`."

    Design: Difficulty/transitive_cascade/buylist_accept_inventory_and_credit_depth2
    """
    cust = create_customer("Accept2 Seller", "accept2@x.com")
    item = create_inventory_item(title="Accept2 Card", market_price_cents=2000)
    sub = create_submitted_buylist(cust, [(item, 2)], payout_method="STORE_CREDIT")
    accepted = validate_success(api.accept_buylist(sub["id"], SM), 200)
    # 2000 * 2 * 0.70 = 2800
    assert accepted["offered_total_cents"] == 2800
    item_after = validate_success(api.get_inventory_item(item["id"], SM), 200)
    assert item_after["quantity_on_hand"] == 2


# ─── priority_pair_validation_conflict / state_beats_fiscal_on_pay (2nd) ────────
def test_pay_unpaid_with_sufficient_credit_succeeds(api):
    """PRD §3.4: "Paying a registration is a customer action that moves
    `payment_status` from `UNPAID` to `PAID`. It is rejected if the registration's
    check-in status is already `WITHDRAWN` (`ERR_INVALID_STATE`), and the customer's
    `store_credit_balance_cents` must be at least the registration's
    `quoted_fee_cents`, otherwise it fails with `ERR_INSUFFICIENT_STORE_CREDIT`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_pay
    """
    set_clock("2026-06-01T00:00:00Z")
    cust = create_customer("Solvent Cust", "solvent@x.com", credit_cents=5000)
    ev = create_open_event(title="Payable Event", format="STANDARD",
                           starts_at="2026-06-10T00:00:00Z",
                           ends_at="2026-06-10T04:00:00Z", capacity=8,
                           entry_fee_cents=2000)
    reg = create_registration(ev, cust)
    # Not WITHDRAWN, credit covers fee: neither the state nor the fiscal guard fires.
    paid = validate_success(
        api.pay_registration(reg["id"], make_customer_headers(cust["id"])), 200)
    assert paid["payment_status"] == "PAID"


# ─── priority_pair_validation_conflict / capacity_beats_quantity_validation (2nd) ─
def test_register_existing_customer_on_full_event_returns_event_full(api):
    """PRD §3.4: "Registration may not be created if it would push the event's
    seated/registered count past `capacity`, which fails with `ERR_EVENT_FULL`."

    Design: Difficulty/priority_pair_validation_conflict/capacity_beats_quantity_validation
    """
    set_clock("2026-06-01T00:00:00Z")
    ca = create_customer("Cap A", "capa@x.com")
    cb = create_customer("Cap B", "capb@x.com")
    ev = create_open_event(title="One Seat 2", format="STANDARD",
                           starts_at="2026-06-10T00:00:00Z",
                           ends_at="2026-06-10T04:00:00Z", capacity=1,
                           entry_fee_cents=1000)
    create_registration(ev, ca)  # fills the seat
    # Existing customer, capacity reached: ERR_EVENT_FULL (no existence failure).
    res = api.create_registration(
        {"event_id": ev["id"], "customer_id": cb["id"]},
        make_customer_headers(cb["id"]))
    validate_error(res, ApiErrorId.ERR_EVENT_FULL)


# ─── boundary_precision_check / allocation_exact_pool_boundary (2nd) ────────────
def test_allocation_exactly_at_pool_succeeds(api):
    """PRD §3.3: "Allocation must not push the release's `quantity_allocated` plus
    this pre-order's `requested_quantity` past the `allocation_pool`; exceeding it
    fails with `ERR_ALLOCATION_EXCEEDED`. ... When allocation succeeds, the pre-order
    moves to `ALLOCATED`, the release's `quantity_allocated` increases by the
    requested quantity"

    Design: Difficulty/boundary_precision_check/allocation_exact_pool_boundary
    """
    ca = create_customer("Exact A", "exacta@x.com", credit_cents=5000)
    cb = create_customer("Exact B", "exactb@x.com", credit_cents=5000)
    rp = create_release_product(title="Exact Box", allocation_pool=5,
                                unit_price_cents=1000, deposit_required_cents=500)
    po_a, rp_after = create_allocated_pre_order(ca, rp, requested_quantity=3,
                                                deposit_paid_cents=500)
    assert rp_after["quantity_allocated"] == 3
    # Second pre-order qty 2: 3+2 = 5 exactly == pool → allowed.
    po_b = create_requested_pre_order(cb, rp, requested_quantity=2, deposit_paid_cents=500)
    allocated = validate_success(
        api.allocate_pre_order(
            po_b["id"], {"expected_release_product_version": rp_after["version"]}, SM),
        200)
    assert allocated["status"] == "ALLOCATED"
    rp_final = validate_success(api.get_release_product(rp["id"], SM), 200)
    assert rp_final["quantity_allocated"] == 5


# ─── boundary_precision_check / empty_buylist_zero_lines_boundary (2nd) ─────────
def test_submit_buylist_with_one_line_succeeds(api):
    """PRD §3.2: "Submitting the draft moves it from `DRAFT` to `SUBMITTED`, but only
    if at least one line exists — an empty submission is rejected with
    `ERR_EMPTY_BUYLIST` — and only if every line's quantity is at least 1"

    Design: Difficulty/boundary_precision_check/empty_buylist_zero_lines_boundary
    """
    cust = create_customer("One Line Seller", "oneline@x.com")
    item = create_inventory_item(title="One Line Card", market_price_cents=500)
    # One line is the count==1 side of the count==0 boundary → submit succeeds.
    sub = create_submitted_buylist(cust, [(item, 1)], payout_method="CASH")
    assert sub["status"] == "SUBMITTED"


# ─── cross_entity_state_dependency / pairing_report_requires_event_in_progress (2nd) ─
def test_report_pairing_while_in_progress_succeeds(api):
    """PRD §3.5: "Reporting a result is a judge-staff action that requires the parent
    event to be `IN_PROGRESS` (otherwise `ERR_INVALID_STATE`) and moves the pairing's
    `result` out of `PENDING`. ... reporting `A_WINS` adds 3 to player A's
    registration `match_points`"

    Design: Difficulty/cross_entity_state_dependency/pairing_report_requires_event_in_progress
    """
    ev, ca, cb, ra, rb = setup_in_progress_event_with_two_players(
        starts_at="2026-08-02T00:00:00Z", ends_at="2026-08-02T05:00:00Z")
    pr = create_pairing(ev, ra, rb)
    reported = validate_success(api.report_pairing(pr["id"], {"result": "A_WINS"}, JUDGE), 200)
    assert reported["result"] == "A_WINS"
    reg_a = validate_success(api.get_registration(ra["id"], SM), 200)
    assert reg_a["match_points"] == 3


# ─── cross_entity_state_dependency / preorder_fulfill_requires_release_live (2nd) ─
def test_fulfill_preorder_after_release_live_succeeds(api):
    """PRD §3.3: "Fulfillment is a store-manager action defined only from
    `ALLOCATED`. The parent release product must be `RELEASED`, or the request fails
    with `ERR_RELEASE_NOT_LIVE`. ... On success the pre-order moves to `FULFILLED`"

    Design: Difficulty/cross_entity_state_dependency/preorder_fulfill_requires_release_live
    """
    cust = create_customer("Live Fulfil", "livefulfil@x.com", credit_cents=100000)
    rp = create_release_product(title="Live Box", allocation_pool=10,
                                unit_price_cents=2000, deposit_required_cents=1000)
    po, rp_after = create_allocated_pre_order(cust, rp, requested_quantity=2,
                                              deposit_paid_cents=1000)
    validate_success(api.release_release_product(rp["id"], SM), 200)
    fulfilled = validate_success(api.fulfill_pre_order(po["id"], SM), 200)
    assert fulfilled["status"] == "FULFILLED"


# ─── resource_temporal_overlap / customer_double_booking_halfopen_overlap (2nd) ─
def test_customer_adjacent_events_allowed(api):
    """PRD §3.4: "the interval is half-open, so two events that merely touch at a
    shared endpoint (one ending exactly when another begins) do not conflict, but any
    true overlap is rejected with `ERR_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/customer_double_booking_halfopen_overlap
    """
    set_clock("2026-06-01T00:00:00Z")
    cust = create_customer("Adjacent Cust", "adjacent@x.com")
    eva = create_open_event(title="Adj A", format="STANDARD",
                            starts_at="2026-06-10T08:00:00Z",
                            ends_at="2026-06-10T12:00:00Z", capacity=8,
                            entry_fee_cents=1000)
    # Event B starts exactly when A ends — adjacency at the shared endpoint.
    evb = create_open_event(title="Adj B", format="MODERN",
                            starts_at="2026-06-10T12:00:00Z",
                            ends_at="2026-06-10T16:00:00Z", capacity=8,
                            entry_fee_cents=1000)
    create_registration(eva, cust)
    reg_b = validate_success(
        api.create_registration({"event_id": evb["id"], "customer_id": cust["id"]},
                                make_customer_headers(cust["id"])), 201)
    assert reg_b["event_id"] == evb["id"]


# ─── resource_temporal_overlap / venue_table_buffer_overlap_on_open (2nd) ───────
def test_venue_non_overlapping_window_opens(api):
    """PRD §3.5: "opening must not cause concurrent play-table usage to exceed 8
    tables over the event's window padded by a 30-minute buffer on each side — that
    is, the window from 30 minutes before `starts_at` to 30 minutes after `ends_at`.
    The buffer-padded window is treated strictly, so adjacency within the buffer is
    not allowed"

    Design: Difficulty/resource_temporal_overlap/venue_table_buffer_overlap_on_open
    """
    set_clock("2026-06-01T00:00:00Z")
    # Big event 8 tables ends 16:00 (padded to 16:30).
    create_open_event(title="Big GP 2", format="STANDARD",
                      starts_at="2026-06-10T12:00:00Z",
                      ends_at="2026-06-10T16:00:00Z", capacity=64,
                      entry_fee_cents=5000, tables_required=8)
    # Second event starts 17:30 (padded window starts 17:00 > 16:30): no overlap.
    side = create_event(title="Clear Side Event", format="COMMANDER",
                        starts_at="2026-06-10T17:30:00Z",
                        ends_at="2026-06-10T19:00:00Z", capacity=8,
                        entry_fee_cents=1000, tables_required=1)
    opened = validate_success(api.open_event(side["id"], SM), 200)
    assert opened["status"] == "OPEN"


# ─── compensating_invariant / buylist_void_restores_inventory_units (2nd) ───────
def test_buylist_void_blocked_when_units_reserved(api):
    """PRD §3.2: "Voiding first checks that for every line, subtracting the line's
    quantity from the mapped item's `quantity_on_hand` would still leave the on-hand
    count at or above the item's `quantity_reserved`; if any line would drive on-hand
    below reserved, the void is rejected with `ERR_INVENTORY_RESERVED`."

    Design: Difficulty/compensating_invariant/buylist_void_restores_inventory_units
    """
    seller = create_customer("Reserve Seller", "reserveseller@x.com")
    item = create_inventory_item(title="Reserved Card", market_price_cents=4000)
    # Accept a buylist of qty 1 → on_hand 1.
    sub = create_submitted_buylist(seller, [(item, 1)], payout_method="CASH")
    validate_success(api.accept_buylist(sub["id"], SM), 200)
    # Reserve that unit via a grading send (quantity_reserved -> 1).
    grader_cust = create_customer("Grader Owner", "graderowner@x.com")
    gs = get_success_data(api.create_grading_submission(
        {"customer_id": grader_cust["id"], "inventory_item_id": item["id"],
         "declared_value_cents": 5000, "service_tier": "ECONOMY"}, SM))
    validate_success(api.send_grading_submission(gs["id"], SM), 200)
    # Voiding would drive on_hand (1) - 1 = 0 below reserved (1) → blocked.
    res = api.void_buylist(sub["id"], SM)
    validate_error(res, ApiErrorId.ERR_INVENTORY_RESERVED)


# NOTE: test_pay_then_withdraw_checked_in_refunds_charged_fee was DELETED.
# Rationale (STEP 1b — non-unique-derivability / BRANCH-ASYMMETRIC SIDE EFFECT):
# PRD §3.4 defines withdraw verbatim as "moves `checkin_status` from `PENDING` to
# `WITHDRAWN`" — a single-source-state transition. A faithful PRD-only implementer
# would therefore define withdraw only from PENDING, on which direct withdrawal of a
# CHECKED_IN registration returns ERR_INVALID_STATE and this test fails. The refund
# clause's "if the registration was checked in → charged_fee_cents" branch is still
# reachable through the §3.5 event-cancel cascade (which withdraws + refunds
# CHECKED_IN registrations), so the cited refund sentence does NOT uniquely determine
# that DIRECT withdrawal of a CHECKED_IN registration succeeds. Two divergent
# PRD-faithful implementations exist, so the test is deleted.
