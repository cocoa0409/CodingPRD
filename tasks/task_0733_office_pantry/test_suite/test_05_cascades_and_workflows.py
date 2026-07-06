"""Multi-hop cascades and cross-entity workflow dependencies:
- subscription.pause -> RC -> Delivery -> Client credit (depth-3+)
- delivery.resolve-dispute -> Client credit (depth-2)
- Cross-entity preconditions on dispatch and rotation-close
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_client_admin_headers, make_location_manager_headers,
    TEST_USERS,
    set_clock, create_plan, create_client, create_location, create_product,
    create_par_level, create_subscription, activate_subscription,
    get_first_rotation_cycle, create_delivery, dispatch_delivery,
    confirm_delivery, dispute_delivery, patch_delivery_line_actual,
    list_delivery_lines, resolve_delivery_dispute,
    pause_subscription,
    setup_scheduled_delivery, setup_disputed_delivery,
    report_all_actuals_and_resolve,
)


# ─────────────────────────────────────────────────────────────
# Difficulty rule 4 — transitive_cascade
# ─────────────────────────────────────────────────────────────

class TestSubscriptionPauseDepth3Cascade:
    def _setup_en_route_delivery(self):
        set_clock("2026-06-01T00:00:00Z")
        plan = create_plan(tier="PC-1", billing_type="FLAT", flat_fee_cents=1000,
                          volume_discount_threshold_headcount=50)
        client = create_client(name="PauseCo-PC", headcount=5)
        loc = create_location(client["id"], name="L-PC", kind="PANTRY", capacity_units=20)
        prod = create_product(sku="P-PC", name="PP", category="SNACK", unit_cost_cents=100)
        create_par_level(loc["id"], prod["id"], 10)
        sub = create_subscription(client["id"], plan["id"], client["version"])
        activate_subscription(sub["id"])
        rc = get_first_rotation_cycle(sub["id"])
        delv = create_delivery(rc["id"], loc["id"], "2026-06-01T12:00:00Z")
        dispatched = dispatch_delivery(delv["id"])
        return {
            "client": client, "loc": loc, "sub": sub, "rc": rc,
            "delivery": dispatched, "prod": prod,
        }

    def test_pause_flips_rotation_cycle_to_invalidated(self, api):
        """PRD §2.7: "that mutation causes the currently-OPEN RotationCycle under the
        subscription to transition from OPEN to INVALIDATED. This is not a separate
        client action; it is a system transition caused by hop 1."

        Design: Difficulty/transitive_cascade/subscription_pause_depth3_cascade
        """
        s = self._setup_en_route_delivery()
        pause_subscription(s["sub"]["id"], s["client"]["id"])
        rc_after = validate_success(api.get_rotation_cycle(s["rc"]["id"], TEST_USERS["platform_admin_headers"]))
        assert rc_after["status"] == "INVALIDATED", \
            f"pause cascade must invalidate the OPEN cycle; got {rc_after['status']!r}"

    def test_pause_cancels_en_route_delivery_and_credits_client(self, api):
        """PRD §2.7: "for each EN_ROUTE delivery cancelled in hop 3 (and only for EN_ROUTE;
        SCHEDULED deliveries cost the client nothing), the cancellation computes
        dispute_credit_cents equal to that delivery's provisional_cents and credits it
        to the client's credit_balance_cents."

        Design: Difficulty/transitive_cascade/subscription_pause_depth3_cascade
        """
        s = self._setup_en_route_delivery()
        # provisional_cents at dispatch: par=10, price=100, PANTRY (no fee), <100 (no disc) => 1000.
        assert s["delivery"]["provisional_cents"] == 1000
        pause_subscription(s["sub"]["id"], s["client"]["id"])

        delv_after = validate_success(api.get_delivery(s["delivery"]["id"], TEST_USERS["platform_admin_headers"]))
        assert delv_after["status"] == "CANCELLED", f"EN_ROUTE delivery must be CANCELLED; got {delv_after['status']!r}"
        assert delv_after["dispute_credit_cents"] == 1000, \
            f"credit should equal provisional; got {delv_after['dispute_credit_cents']}"

        client_after = validate_success(api.get_client(s["client"]["id"], TEST_USERS["platform_admin_headers"]))
        assert client_after["credit_balance_cents"] == 1000, \
            f"client credit must equal provisional after hop-4; got {client_after['credit_balance_cents']}"


class TestDeliveryResolveDisputeDepth2Credit:
    def _dispute_setup(self, planned_units: int = 10, actual_units: int = 6, unit_cost_cents: int = 100):
        set_clock("2026-06-01T00:00:00Z")
        plan = create_plan(tier="DIS-1", billing_type="FLAT", flat_fee_cents=1000,
                          volume_discount_threshold_headcount=50)
        client = create_client(name="DisCo-DIS", headcount=5)
        loc = create_location(client["id"], name="L-DIS", kind="PANTRY", capacity_units=20)
        prod = create_product(sku="D-DIS", name="D", category="SNACK", unit_cost_cents=unit_cost_cents)
        create_par_level(loc["id"], prod["id"], planned_units)
        sub = create_subscription(client["id"], plan["id"], client["version"])
        activate_subscription(sub["id"])
        rc = get_first_rotation_cycle(sub["id"])
        delv = create_delivery(rc["id"], loc["id"], "2026-06-01T12:00:00Z")
        dispatch_delivery(delv["id"])
        confirm_delivery(delv["id"], loc["id"])
        dispute_delivery(delv["id"], loc["id"], "shortship")
        lines = list_delivery_lines(delv["id"])
        patch_delivery_line_actual(lines[0]["id"], loc["id"], actual_units)
        return {"client": client, "loc": loc, "delivery": delv}

    def test_resolve_computes_final_and_credit(self, api):
        """PRD §3.6: "Resolve requires the delivery to be DISPUTED and requires
        actuals-set on every line; it then computes final_cents under the chronological
        variant and computes dispute_credit_cents as the sum over all lines where
        actual_units is strictly less than planned_units of the quantity
        (planned_units - actual_units) multiplied by unit_price_cents_snapshot."

        Design: Difficulty/transitive_cascade/delivery_resolve_dispute_depth2_credit
        """
        s = self._dispute_setup(planned_units=10, actual_units=6, unit_cost_cents=100)
        resolved = resolve_delivery_dispute(s["delivery"]["id"])
        # provisional: 10*100 = 1000; final: 6*100 = 600; credit: (10-6)*100 = 400.
        assert resolved["provisional_cents"] == 1000
        assert resolved["final_cents"] == 600
        assert resolved["dispute_credit_cents"] == 400
        assert resolved["status"] == "FINALIZED"

    def test_resolve_credits_client_credit_balance(self, api):
        """PRD §3.6: "Resolve then credits client.credit_balance_cents by exactly
        dispute_credit_cents and flips the delivery's status to FINALIZED."
        PRD §2.7: "The Delivery resolve-dispute path is a shallower, second-depth cascade:
        computing dispute_credit_cents at resolve time itself causes the client's
        credit_balance_cents to be incremented."

        Design: Difficulty/transitive_cascade/delivery_resolve_dispute_depth2_credit
        """
        s = self._dispute_setup(planned_units=10, actual_units=6, unit_cost_cents=100)
        resolve_delivery_dispute(s["delivery"]["id"])
        client_after = validate_success(api.get_client(s["client"]["id"], TEST_USERS["platform_admin_headers"]))
        assert client_after["credit_balance_cents"] == 400, \
            f"client credit must equal dispute_credit_cents 400; got {client_after['credit_balance_cents']}"


# ─────────────────────────────────────────────────────────────
# Difficulty rule 7 — cross_entity_state_dependency
# ─────────────────────────────────────────────────────────────

def test_dispatch_after_pause_is_rejected(api):
    """PRD §3.5: "Dispatch requires the delivery to be SCHEDULED, the parent subscription's
    status to be ACTIVE (ERR_SUBSCRIPTION_NOT_ACTIVE), the parent rotation cycle's status
    to be OPEN, and the current clock to be less than 24 hours past scheduled_at — that
    is, the dispatch window closes exactly 24 hours after the scheduled time."
    PRD §2.11: "The target entity is not in a state from which the requested transition
    is valid ... ERR_INVALID_STATE (409)."

    Design: Difficulty/cross_entity_state_dependency/delivery_dispatch_after_pause_cascade_precondition_pair
    """
    state = setup_scheduled_delivery(
        clock="2026-06-01T00:00:00Z",
        scheduled_at="2026-06-01T12:00:00Z",
    )
    pause_subscription(state["subscription"]["id"], state["client"]["id"])
    # After pause: delivery is CANCELLED (state axis) and subscription is PAUSED (cross-entity axis).
    # Priority 12 (state) wins over priority 13 (subscription-not-active).
    res = api.dispatch_delivery(state["delivery"]["id"], TEST_USERS["platform_admin_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_close_rotation_with_non_terminal_delivery_rejected(api):
    """PRD §3.7: "Close requires the cycle to be OPEN, requires every delivery under the
    cycle to be FINALIZED or CANCELLED, requires the current clock to be at least
    effective_to on the cycle, and requires the parent subscription's status to be
    either ACTIVE or PAUSED."

    Design: Difficulty/cross_entity_state_dependency/rotation_close_requires_all_deliveries_terminal
    """
    state = setup_scheduled_delivery(
        clock="2026-06-01T00:00:00Z",
        scheduled_at="2026-06-05T00:00:00Z",
    )
    # Dispatch so delivery is EN_ROUTE (still non-terminal).
    dispatch_delivery(state["delivery"]["id"])
    # Advance past the RC window (30 days from 2026-06-01).
    set_clock("2026-07-05T00:00:00Z")
    res = api.close_rotation_cycle(state["rotation_cycle"]["id"], TEST_USERS["platform_admin_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_dispatch_requires_active_subscription_via_cross_entity(api):
    """PRD §2.11 (priority 13): "Cross-entity active subscription. Dispatch and confirm
    require the parent subscription's status to be ACTIVE — ERR_SUBSCRIPTION_NOT_ACTIVE (409)."

    Two variants: after subscription is cancelled from PAUSED (skipping the cascade), the
    delivery entity itself may already be CANCELLED. For this instance we exercise a
    scenario where the priority-13 cross-entity check would surface if state (priority 12)
    did not preempt it: since pause cascades to cancel the SCHEDULED delivery, ERR_INVALID_STATE
    (priority 12) is the observable error — this test asserts priority 12 wins, which is
    the entire point of the Rule 7 evidence.

    Design: Difficulty/cross_entity_state_dependency/delivery_dispatch_after_pause_cascade_precondition_pair
    """
    state = setup_scheduled_delivery(
        clock="2026-06-01T00:00:00Z",
        scheduled_at="2026-06-01T12:00:00Z",
    )
    pause_subscription(state["subscription"]["id"], state["client"]["id"])
    # Both preconditions violated: subscription is PAUSED (not ACTIVE); delivery is CANCELLED
    # (not SCHEDULED). PRD priority ordering must surface the state (priority 12) error, not
    # the cross-entity subscription-not-active (priority 13) one.
    res = api.dispatch_delivery(state["delivery"]["id"], TEST_USERS["platform_admin_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_close_rejects_open_cycle_before_effective_to(api):
    """PRD §3.7: "requires the current clock to be at least effective_to on the cycle."

    Design: Difficulty/cross_entity_state_dependency/rotation_close_requires_all_deliveries_terminal
    """
    # Fresh active subscription with clock at 2026-06-01. RC window is [2026-06-01, 2026-07-01).
    # Try to close BEFORE effective_to (clock still at 2026-06-01). No deliveries, so
    # priority 12 (state precondition on OPEN_to_CLOSED, which requires clock>=effective_to)
    # must fire; expect ERR_INVALID_STATE.
    from test_helpers import setup_active_subscription
    state = setup_active_subscription(clock="2026-06-01T00:00:00Z")
    # Do NOT advance the clock past effective_to.
    res = api.close_rotation_cycle(state["rotation_cycle"]["id"], TEST_USERS["platform_admin_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
