"""State-machine transitions, invalid transitions, and cyclic/parallel dimensions."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_client_admin_headers, make_location_manager_headers,
    TEST_USERS,
    set_clock, create_plan, create_client, create_location, create_product,
    create_par_level, create_subscription, activate_subscription,
    get_first_rotation_cycle,
    setup_active_subscription, setup_scheduled_delivery, setup_delivered_delivery,
    pause_subscription, resume_subscription, cancel_subscription,
    dispatch_delivery, confirm_delivery, create_delivery,
    close_and_get_invoice, pay_invoice,
)


# ─────────────────────────────────────────────────────────────
# Difficulty rule 3 — non_linear_state_machine
# ─────────────────────────────────────────────────────────────

class TestSubscriptionPauseResumeCycle:
    def test_subscription_can_cycle_active_paused_active(self, api):
        """PRD §3.3: "The client admin can pause an ACTIVE subscription."
        PRD §3.3: "The client admin can resume a PAUSED subscription. Resume flips
        status back to ACTIVE, clears paused_at to null."

        Design: Difficulty/non_linear_state_machine/subscription_pause_resume_cycle
        """
        state = setup_active_subscription()
        sub = state["subscription"]
        client = state["client"]
        assert sub["status"] == "ACTIVE", f"pre: expected ACTIVE, got {sub['status']!r}"

        paused = pause_subscription(sub["id"], client["id"])
        assert paused["status"] == "PAUSED", f"after pause: expected PAUSED, got {paused['status']!r}"

        resumed = resume_subscription(sub["id"], client["id"])
        assert resumed["status"] == "ACTIVE", \
            f"after resume: expected ACTIVE (cyclic), got {resumed['status']!r}"

    def test_resume_opens_new_rotation_cycle(self, api):
        """PRD §3.3: "Resume flips status back to ACTIVE, clears paused_at to null,
        and opens a new RotationCycle with cycle_index equal to the previous cycle's
        index plus one."

        Design: Difficulty/non_linear_state_machine/subscription_pause_resume_cycle
        """
        state = setup_active_subscription()
        sub = state["subscription"]
        client = state["client"]
        rc_initial = state["rotation_cycle"]
        assert rc_initial["cycle_index"] == 1

        pause_subscription(sub["id"], client["id"])
        # Advance the clock so the new cycle window is disjoint from the invalidated one.
        set_clock("2026-07-15T00:00:00Z")
        resume_subscription(sub["id"], client["id"])

        # List cycles again; there must now be a new OPEN cycle with cycle_index=2.
        res = api.list_subscription_rotation_cycles(sub["id"], TEST_USERS["platform_admin_headers"])
        rcs = get_success_data(res)
        if isinstance(rcs, dict):
            rcs = [rcs]
        indices = sorted(rc["cycle_index"] for rc in rcs)
        assert 2 in indices, f"resume must open a new RC with cycle_index=2, got {indices}"


class TestInvoiceParallelDimensions:
    def test_paying_invoice_flips_payment_status_but_not_dispute_status(self, api):
        """PRD §3.7: "The invoice's payment_status is UNPAID on creation and its
        dispute_status is CLEAN on creation. These two enumerations move on
        independent dimensions."
        PRD §3.7: "The client admin marks an invoice paid by moving payment_status
        from UNPAID to PAID."

        Design: Difficulty/non_linear_state_machine/invoice_parallel_payment_dispute_dimensions
        """
        set_clock("2026-06-01T00:00:00Z")
        state = setup_active_subscription(
            plan_overrides={
                "tier": "FLAT-A", "billing_type": "FLAT", "flat_fee_cents": 3000,
                "volume_discount_threshold_headcount": 50,
            },
            client_overrides={"name": "ParaCo", "headcount": 12},
        )
        state = close_and_get_invoice(state, close_clock="2026-07-05T00:00:00Z")
        inv = state["invoice"]
        assert inv["payment_status"] == "UNPAID"
        assert inv["dispute_status"] == "CLEAN"

        paid = pay_invoice(inv["id"], state["client"]["id"])
        assert paid["payment_status"] == "PAID", \
            f"after pay: payment_status should be PAID, got {paid['payment_status']!r}"
        assert paid["dispute_status"] == "CLEAN", \
            f"payment must not disturb dispute dimension; got dispute_status={paid['dispute_status']!r}"

    def test_paying_uses_independent_axis_from_dispute_axis(self, api):
        """PRD §3.7: "Payment does not disturb dispute state and vice versa."

        Design: Difficulty/non_linear_state_machine/invoice_parallel_payment_dispute_dimensions
        """
        set_clock("2026-06-01T00:00:00Z")
        state = setup_active_subscription(
            plan_overrides={"tier": "FLAT-B", "billing_type": "FLAT", "flat_fee_cents": 2500,
                            "volume_discount_threshold_headcount": 50},
        )
        state = close_and_get_invoice(state, close_clock="2026-07-05T00:00:00Z")
        inv = state["invoice"]
        # Two axes: verify both start at their initial states — this is the parallel-dimensions claim.
        assert inv["payment_status"] == "UNPAID"
        assert inv["dispute_status"] == "CLEAN"
        # And after payment, dispute axis remains CLEAN (independence check).
        paid = pay_invoice(inv["id"], state["client"]["id"])
        assert paid["dispute_status"] == "CLEAN", \
            "dispute_status must not change on pay (parallel dimensions)"


# ─────────────────────────────────────────────────────────────
# Corner/state_machines
# ─────────────────────────────────────────────────────────────

def test_cancel_from_cancelled_returns_invalid_state(api):
    """PRD §3.3: "CANCELLED is the sole terminal state for a subscription; there is no reopen."
    PRD §2.11: "The target entity is not in a state from which the requested transition is valid,
    or a rotation cycle referenced by a delivery-generator call is not OPEN — ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/cancel_from_cancelled_returns_invalid_state
    """
    state = setup_active_subscription()
    sub = state["subscription"]
    client = state["client"]
    cancel_subscription(sub["id"], client["id"])
    # Second cancel from CANCELLED must fail.
    res = api.cancel_subscription(sub["id"], make_client_admin_headers(client["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_activate_already_active_subscription_rejected(api):
    """PRD §3.3: "Activation is a platform-admin operation on a DRAFT subscription."
    PRD §2.11: "The target entity is not in a state from which the requested transition is valid ...
    ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/activate_already_active_subscription_rejected
    """
    state = setup_active_subscription()
    res = api.activate_subscription(state["subscription"]["id"], TEST_USERS["platform_admin_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_dispute_after_48h_window_closed_rejected(api):
    """PRD §3.6: "Dispute requires the delivery to be DELIVERED, the manager's X-User-ID
    to match the delivery's location_id, and the current clock to be strictly less than
    48 hours past delivered_at."

    Design: Corner/state_machines/dispute_after_48h_window_closed_rejected
    """
    state = setup_delivered_delivery(
        clock="2026-06-01T00:00:00Z",
        scheduled_at="2026-06-01T10:00:00Z",
    )
    # Advance clock strictly more than 48h past delivered_at (~2026-06-01T10:xx). Use 3 days later.
    set_clock("2026-06-04T00:00:00Z")
    res = api.dispute_delivery(
        state["delivery"]["id"],
        {"dispute_reason": "too late"},
        make_location_manager_headers(state["location"]["id"]),
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_pause_cascade_leaves_delivered_delivery_untouched(api):
    """PRD §2.7: "the INVALIDATED mutation on the rotation cycle causes every Delivery
    under that cycle whose status is SCHEDULED or EN_ROUTE to transition to CANCELLED.
    Terminal deliveries (DELIVERED, DISPUTED, FINALIZED, previously CANCELLED) are not touched."

    Design: Corner/state_machines/cascade_only_cancels_non_terminal_deliveries_on_pause
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(tier="PP-1", billing_type="FLAT", flat_fee_cents=1000,
                      volume_discount_threshold_headcount=10)
    client = create_client(name="PPC", headcount=5)
    loc1 = create_location(client["id"], name="L1", kind="PANTRY", capacity_units=5)
    loc2 = create_location(client["id"], name="L2", kind="PANTRY", capacity_units=5)
    prod = create_product(sku="P-CC", name="P", category="SNACK", unit_cost_cents=100)
    create_par_level(loc1["id"], prod["id"], 1)
    create_par_level(loc2["id"], prod["id"], 1)
    sub = create_subscription(client["id"], plan["id"], client["version"])
    activate_subscription(sub["id"])
    rc = get_first_rotation_cycle(sub["id"])

    # Delivery A at loc1 -> dispatch -> confirm -> DELIVERED.
    delv_a = create_delivery(rc["id"], loc1["id"], "2026-06-01T10:00:00Z")
    dispatch_delivery(delv_a["id"])
    confirm_delivery(delv_a["id"], loc1["id"])

    # Delivery B at loc2 (different location so 24h buffer at loc1 is not violated) — stays SCHEDULED.
    delv_b = create_delivery(rc["id"], loc2["id"], "2026-06-02T10:00:00Z")

    # Pause the subscription — cascade must cancel B but not touch A.
    pause_subscription(sub["id"], client["id"])

    got_a = validate_success(api.get_delivery(delv_a["id"], TEST_USERS["platform_admin_headers"]))
    got_b = validate_success(api.get_delivery(delv_b["id"], TEST_USERS["platform_admin_headers"]))
    assert got_a["status"] == "DELIVERED", \
        f"DELIVERED delivery A must survive pause cascade, got {got_a['status']!r}"
    assert got_b["status"] == "CANCELLED", \
        f"SCHEDULED delivery B must be cancelled by pause cascade, got {got_b['status']!r}"
