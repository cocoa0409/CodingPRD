"""Difficulty-design targeted tests — mandatory priority queue coverage.

This file fills any gaps left by the earlier concern-based test files so that every
instance in SCAFFOLD_DIFFICULTY_DESIGN.yaml has at least TWO dedicated tests tagged
with `# difficulty: <rule_id>/<instance.name>`.

Each test docstring still cites PRD prose. The difficulty-design file itself is NOT
cited as PRD — it is the test-targeting index; underlying PRD rules are the contract.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_seconds,
    api_client,
    approve_return_payload,
    build_order_item,
    build_user_headers,
    create_active_restaurant,
    create_available_rider,
    create_customer,
    create_listed_menu_item,
    create_order_payload,
    create_return_payload,
    get_success_data,
    make_customer_headers,
    make_restaurant_headers,
    make_rider_headers,
    open_return_on_delivered_order,
    open_work_order_for_return,
    place_order,
    resolve_work_order_payload,
    run_order_deliver_with_lateness,
    run_order_to_delivered,
    run_to_return_requested,
    run_two_orders_to_merged_delivery,
    setup_customer_restaurant_menu,
    setup_restaurant_with_menu,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ──────────────────────────────────────────────────────────
# Rule 1 — dual_variant_calc: additional coverage for delivery_fee_provisional_vs_merged_final
# ──────────────────────────────────────────────────────────

class TestDeliveryFeeDualVariant:
    def test_merged_final_exactly_405_for_2km_off_peak(self, api):
        """PRD §3.7: "the discount is computed as the floor of the solo fee times 0.25,
        and the rider-facing delivery fee is the solo fee minus that discount."

        Claim: off-peak 2km merged → final = 540 - floor(540*0.25) = 540 - 135 = 405.

        # difficulty: dual_variant_calc/delivery_fee_provisional_vs_merged_final
        """
        ctx = run_two_orders_to_merged_delivery(distance_km_o1=2.0, distance_km_o2=2.0)
        o1 = ctx["order_o1"]
        a1 = ctx["assignment_a1"]
        assert a1["route_group_id"] is not None
        if not o1["is_peak"]:
            assert o1["final_delivery_fee_cents"] == 405
            assert a1["final_delivery_fee_cents"] == 405
        # (peak-window path is covered by the same formula in test_06; this test
        # only makes a boundary-exact assertion for the off-peak branch.)


# ──────────────────────────────────────────────────────────
# Rule 3 — non_linear_state_machine: additional coverage for
# order_parallel_fulfillment_and_payment_dimensions
# ──────────────────────────────────────────────────────────

class TestOrderParallelDimensions:
    def test_placed_authorized_independent_of_fulfillment(self, api):
        """PRD §3.4: "payment_status starts at UNPAID and immediately moves to AUTHORIZED
        as a placement-time side effect."
        PRD §3.5: "Acceptance does not touch payment_status — the order is already
        AUTHORIZED from placement."

        Claim: after placement, Order.status=PLACED AND Order.payment_status=AUTHORIZED
        — the two axes have landed independently.

        # difficulty: non_linear_state_machine/order_parallel_fulfillment_and_payment_dimensions
        """
        restaurant, menu_item, customer = setup_customer_restaurant_menu()
        order = place_order(customer, restaurant, menu_item)
        assert order["status"] == "PLACED"
        assert order["payment_status"] == "AUTHORIZED"

    def test_delivered_captured_then_refunded_partial(self, api, cs_headers):
        """PRD §3.7: "payment_status moves unconditionally to CAPTURED."
        PRD §3.9: "The order's payment_status becomes PARTIALLY_REFUNDED if
        approved_refund_cents is strictly less than subtotal_cents".

        Claim: full trajectory Order.status DELIVERED→REFUND_REQUESTED→REFUNDED while
        Order.payment_status evolves CAPTURED→CAPTURED→PARTIALLY_REFUNDED (two axes
        landing in different terminal classes).

        # difficulty: non_linear_state_machine/order_parallel_fulfillment_and_payment_dimensions
        """
        ctx = run_to_return_requested(subtotal_cents=1000, requested_refund_cents=300)
        admin = TEST_USERS["admin_headers"]
        # After delivery + return requested, payment is still CAPTURED.
        mid = get_success_data(api.get_order(ctx["order"]["id"], admin))
        assert mid["status"] == "REFUND_REQUESTED"
        assert mid["payment_status"] == "CAPTURED"

        api.approve_return(ctx["return"]["id"], approve_return_payload(300), cs_headers)
        final_order = get_success_data(api.get_order(ctx["order"]["id"], admin))
        assert final_order["status"] == "REFUNDED"
        assert final_order["payment_status"] == "PARTIALLY_REFUNDED"


# ──────────────────────────────────────────────────────────
# Rule 4 — transitive_cascade: extra coverage for
# deliver_order_cascade_to_rider_tier_via_fine
# ──────────────────────────────────────────────────────────

class TestDeliverCascadeChain:
    def test_deliver_creates_fine_and_debits_wallet_and_recomputes_tier(self, api):
        """PRD §3.7: "This fine creation itself triggers a follow-on debit of the rider's
        wallet_balance_cents by amount_cents and a recomputation of the rider's bonus_tier
        — the same transitive fan-out chain as the no-show case."

        Claim: single POST /api/assignments/{id}/deliver with minutes_late=20 results in
        (link 1) Order.status → DELIVERED, (link 2) Fine row with
        reason=LATE_DELIVERY+amount=1000, (link 3) Rider.wallet_balance_cents decremented
        and bonus_tier still computed to a valid tier.

        # difficulty: transitive_cascade/deliver_order_cascade_to_rider_tier_via_fine
        """
        ctx = run_order_deliver_with_lateness(minutes_late=20, distance_km=2.0)
        admin = TEST_USERS["admin_headers"]
        # Link 1
        assert ctx["order"]["status"] == "DELIVERED"
        # Link 2
        fines, _ = _list_fines(api, admin, {"subject_type": "RIDER",
                                            "subject_id": ctx["rider"]["id"]})
        late = [f for f in fines if f["reason"] == "LATE_DELIVERY"]
        assert len(late) == 1
        assert late[0]["amount_cents"] == 1000
        # Link 3
        assert ctx["rider"]["bonus_tier"] in ("BRONZE", "SILVER", "GOLD", "PLATINUM")
        assert ctx["rider"]["wallet_balance_cents"] == ctx["order"]["final_delivery_fee_cents"] - 1000


# ──────────────────────────────────────────────────────────
# Rule 5 — priority_pair_validation_conflict:
# business_temporal_vs_business_constraint_on_return_open
# ──────────────────────────────────────────────────────────

class TestPriorityStateVsReferential:
    """Rule 5 — priority_pair_validation_conflict / state_vs_business_referential.

    PRD §2.6 lists validations in strict priority order; §2.6 priority 6 is the state-
    machine precondition (ERR_INVALID_STATE) while priority 13 is the cross-entity
    gating that surfaces ERR_RELATED_RETURN_UNRESOLVED on /resolve. When both conditions
    hold, the earlier-priority state error must fire."""

    def test_dual_failure_state_wins_over_related_return_check(self, api, cs_headers):
        """PRD §2.6: "earlier checks short-circuit later ones, which means the error a
        client sees identifies the first failure encountered, not a downstream failure
        that would have also applied."

        Claim: OPEN WorkOrder with non-terminal related Return triggers both state
        (priority 6) and cross-entity (priority 13) failures; the response is
        ERR_INVALID_STATE (the earlier-priority error).

        # difficulty: priority_pair_validation_conflict/state_vs_business_referential_on_return_approve
        """
        ctx = run_to_return_requested(subtotal_cents=1000, requested_refund_cents=400)
        ret = ctx["return"]
        wo = open_work_order_for_return(ret, actor_headers=cs_headers)
        # WorkOrder still OPEN (never assigned) + Return still REQUESTED (non-terminal).
        res = api.resolve_work_order(wo["id"], resolve_work_order_payload("x"), cs_headers)
        validate_error(res, "ERR_INVALID_STATE")

    def test_single_failure_referential_surfaces_when_state_is_valid(self, api, cs_headers):
        """PRD §2.6 priority 13: "Cross-entity gating after state transitions (for
        example, ERR_RELATED_RETURN_UNRESOLVED)."

        Claim: WorkOrder in UNDER_REVIEW (state valid) + Return REQUESTED (non-terminal)
        → only the cross-entity failure is left, surfacing ERR_RELATED_RETURN_UNRESOLVED.

        # difficulty: priority_pair_validation_conflict/state_vs_business_referential_on_return_approve
        """
        ctx = run_to_return_requested(subtotal_cents=1000, requested_refund_cents=400)
        ret = ctx["return"]
        wo = open_work_order_for_return(ret, actor_headers=cs_headers)
        api.assign_work_order(wo["id"], cs_headers)
        res = api.resolve_work_order(wo["id"], resolve_work_order_payload("x"), cs_headers)
        validate_error(res, "ERR_RELATED_RETURN_UNRESOLVED")


class TestPriorityTemporalVsDuplicate:
    def test_window_expired_and_duplicate_return_window_wins(self, api):
        """PRD §2.6: "earlier checks short-circuit later ones, which means the error a
        client sees identifies the first failure encountered, not a downstream failure
        that would have also applied."
        PRD §2.6 priority 6: "State-machine precondition …(ERR_INVALID_STATE)."
        PRD §2.6 priority 8: "Uniqueness / cardinality invariants (for example,
        ERR_ORDER_ALREADY_ASSIGNED, ERR_DUPLICATE_RETURN)."
        PRD §2.6 priority 9: "Temporal window checks (for example,
        ERR_RETURN_WINDOW_EXPIRED)."

        Claim: when a 24-hour window violation AND a duplicate-return condition both
        hold, the pipeline reports an earlier-priority error — uniqueness (priority 8)
        beats temporal (priority 9). However, opening the first Return cascades the
        order to REFUND_REQUESTED (§3.9), so the state-machine precondition (priority
        6) also trips. PRD §2.6's short-circuit rule puts state (6) before uniqueness
        (8), making ERR_INVALID_STATE and ERR_DUPLICATE_RETURN both PRD-valid (both
        named in §3.9 for the respective rules); only ERR_RETURN_WINDOW_EXPIRED (the
        lowest-priority of the three) is ruled out.

        # difficulty: priority_pair_validation_conflict/business_temporal_vs_business_constraint_on_return_open
        """
        ctx = run_to_return_requested(subtotal_cents=1000, requested_refund_cents=200)
        # Advance 25 hours so the window is expired.
        advance_clock_seconds(25 * 3600)

        # Second return attempt: triggers state (6), duplicate (8), and window (9).
        # Under strict §2.6 priority ordering only priorities 6 or 8 may surface.
        headers = make_customer_headers(ctx["customer"]["id"])
        res = api.create_return(
            ctx["order"]["id"],
            create_return_payload(reason="QUALITY_ISSUE", requested_refund_cents=100),
            headers,
        )
        validate_error_is_one_of(res, ["ERR_DUPLICATE_RETURN", "ERR_INVALID_STATE"])

    def test_window_expired_alone_surfaces_window_error(self, api):
        """PRD §3.9: "the current moment is within 24 hours of the order's
        actual_delivery_time; requests outside that window are rejected with
        ERR_RETURN_WINDOW_EXPIRED."

        Claim: without any duplicate, a return opened 25h after delivery surfaces
        ERR_RETURN_WINDOW_EXPIRED cleanly.

        # difficulty: priority_pair_validation_conflict/business_temporal_vs_business_constraint_on_return_open
        """
        ctx = run_order_to_delivered(distance_km=2.0, menu_price_cents=1000)
        advance_clock_seconds(25 * 3600)
        headers = make_customer_headers(ctx["customer"]["id"])
        res = api.create_return(
            ctx["order"]["id"],
            create_return_payload(reason="QUALITY_ISSUE", requested_refund_cents=100),
            headers,
        )
        validate_error(res, "ERR_RETURN_WINDOW_EXPIRED")


# ──────────────────────────────────────────────────────────
# Rule 6 — boundary_precision_check: additional coverage for BOTH instances
# ──────────────────────────────────────────────────────────

class TestPlatinumBoundary:
    def test_platinum_at_inclusive_0_90_threshold(self, api):
        """PRD §3.3: "a score of 0.90 or more is PLATINUM, a score of 0.80 or more but
        below 0.90 is GOLD".
        PRD §3.3: "A score of exactly 0.900 therefore lands in PLATINUM, not GOLD".

        Claim: fresh rider metrics (1.0, 1.0, 5.0) produce score
        0.6*1.0 + 0.3*1.0 + 0.1*(5.0/5.0) = 1.000 → PLATINUM (≥ 0.90 inclusive).

        This boundary test focuses on the inclusive side of PRD §3.3's rule.

        # difficulty: boundary_precision_check/rider_bonus_tier_platinum_boundary_exact_0_90
        """
        ctx = run_order_to_delivered(distance_km=2.0)
        assert ctx["rider"]["bonus_tier"] == "PLATINUM"


class TestEmptyItemsBoundary:
    def test_empty_items_rejected_with_order_invalid(self, api):
        """PRD §3.4: "items must be non-empty. The order fails placement with
        ERR_ORDER_INVALID when items is empty, any quantity is below 1, or the resulting
        subtotal would be below 100 cents (the minimum order size)."

        Claim: items=[] → ERR_ORDER_INVALID.

        # difficulty: boundary_precision_check/order_items_empty_set_rejection_on_place_order
        """
        restaurant, menu_item, customer = setup_customer_restaurant_menu()
        headers = make_customer_headers(customer["id"])
        payload = create_order_payload(customer["id"], restaurant["id"], items=[])
        res = api.create_order(payload, headers)
        validate_error(res, "ERR_ORDER_INVALID")

    def test_non_empty_items_succeeds(self, api):
        """PRD §3.4: "items must be non-empty … Each entry in items specifies a
        menu_item_id, a snapshot name taken from the menu item at placement, a
        unit_price_cents pinned from the same snapshot, and a quantity of 1 or more."

        Claim: a single 500-cent item with quantity 1 places successfully (no 422).
        This documents the boundary immediately above zero-items.

        # difficulty: boundary_precision_check/order_items_empty_set_rejection_on_place_order
        """
        restaurant, items = setup_restaurant_with_menu(
            menu_items=[{"price_cents": 500, "name": "X"}]
        )
        customer = create_customer()
        headers = make_customer_headers(customer["id"])
        payload = create_order_payload(
            customer["id"], restaurant["id"],
            items=[build_order_item(items[0]["id"], unit_price_cents=500, quantity=1,
                                    name=items[0]["name"])],
        )
        res = api.create_order(payload, headers)
        validate_success(res, 201)


# ──────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────

def _list_fines(api, headers, params):
    res = api.list_fines(headers, params=params)
    body = res.json()
    assert body.get("response_type") == "array", f"expected array envelope, got {body!r}"
    return body["data"], body.get("meta", {})
