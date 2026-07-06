"""Conserved-quantity invariants (money, time) and cross-cutting complexity:
OCC stale-version, version bumps, overdue-invoice sweep."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    make_client_admin_headers, make_location_manager_headers,
    TEST_USERS,
    set_clock, create_plan, create_client, create_location, create_product,
    create_par_level, create_subscription, activate_subscription,
    get_first_rotation_cycle,
    dispatch_delivery, confirm_delivery, dispute_delivery,
    patch_delivery_line_actual, list_delivery_lines, resolve_delivery_dispute,
    pause_subscription, resume_subscription,
    setup_active_subscription, close_and_get_invoice,
    assert_delivery_money_conservation,
)


# ─────────────────────────────────────────────────────────────
# Difficulty rule 9 — compensating_invariant
# ─────────────────────────────────────────────────────────────

class TestMoneyConservationOnDisputeCycle:
    def _resolve_dispute_with_shortship(self, planned_units=10, actual_units=7, unit_cost_cents=100):
        set_clock("2026-06-01T00:00:00Z")
        plan = create_plan(tier="MC-1", billing_type="FLAT", flat_fee_cents=1000,
                          volume_discount_threshold_headcount=50)
        client = create_client(name="Money-MC", headcount=5)
        loc = create_location(client["id"], name="L-MC", kind="PANTRY", capacity_units=20)
        prod = create_product(sku="M-MC", name="M", category="SNACK", unit_cost_cents=unit_cost_cents)
        create_par_level(loc["id"], prod["id"], planned_units)
        sub = create_subscription(client["id"], plan["id"], client["version"])
        activate_subscription(sub["id"])
        rc = get_first_rotation_cycle(sub["id"])
        from test_helpers import create_delivery
        delv = create_delivery(rc["id"], loc["id"], "2026-06-02T00:00:00Z")
        dispatch_delivery(delv["id"])
        confirm_delivery(delv["id"], loc["id"])
        dispute_delivery(delv["id"], loc["id"], "short")
        lines = list_delivery_lines(delv["id"])
        patch_delivery_line_actual(lines[0]["id"], loc["id"], actual_units)
        resolved = resolve_delivery_dispute(delv["id"])
        return resolved

    def test_provisional_equals_final_plus_credit(self, api):
        """PRD §3.6: "the credit is the unit shortfall priced at the same snapshotted
        per-unit cost the billing engine uses — no service-fee overlay and no
        bulk-discount overlay applies to the credit."
        PRD §3.5: "The provisional variant, evaluated at dispatch, walks each DeliveryLine
        for the delivery and computes three per-line quantities from three inputs plus
        the parent location's kind."

        Design: Difficulty/compensating_invariant/money_conservation_delivery_dispute_cycle
        """
        d = self._resolve_dispute_with_shortship(planned_units=10, actual_units=7, unit_cost_cents=100)
        # provisional = 10*100 = 1000 (PANTRY, no fee; <100, no discount)
        # final = 7*100 = 700; credit = (10-7)*100 = 300
        assert d["provisional_cents"] == 1000, f"provisional: {d['provisional_cents']}"
        assert d["final_cents"] == 700, f"final: {d['final_cents']}"
        assert d["dispute_credit_cents"] == 300, f"credit: {d['dispute_credit_cents']}"
        # The invariant that ties them together:
        assert_delivery_money_conservation(d)

    def test_client_credit_balance_equals_delivery_credit(self, api):
        """PRD §3.6: "Resolve then credits client.credit_balance_cents by exactly
        dispute_credit_cents and flips the delivery's status to FINALIZED."

        Design: Difficulty/compensating_invariant/money_conservation_delivery_dispute_cycle
        """
        d = self._resolve_dispute_with_shortship(planned_units=10, actual_units=7, unit_cost_cents=100)
        # Grab client id from the delivery's rotation cycle. We know we made a fresh client;
        # find it via listing (only one client). Use listing not by handle since we didn't return it.
        # Simpler: rebuild the flow and capture the client id.
        # For this test we re-run the setup to keep the code straight.
        set_clock("2026-06-01T00:00:00Z")
        plan = create_plan(tier="MC-2", billing_type="FLAT", flat_fee_cents=1000,
                          volume_discount_threshold_headcount=50)
        client = create_client(name="Money-MC2", headcount=5)
        loc = create_location(client["id"], name="L-MC2", kind="PANTRY", capacity_units=20)
        prod = create_product(sku="M-MC2", name="M", category="SNACK", unit_cost_cents=100)
        create_par_level(loc["id"], prod["id"], 10)
        sub = create_subscription(client["id"], plan["id"], client["version"])
        activate_subscription(sub["id"])
        rc = get_first_rotation_cycle(sub["id"])
        from test_helpers import create_delivery
        delv = create_delivery(rc["id"], loc["id"], "2026-06-02T00:00:00Z")
        dispatch_delivery(delv["id"])
        confirm_delivery(delv["id"], loc["id"])
        dispute_delivery(delv["id"], loc["id"], "short")
        lines = list_delivery_lines(delv["id"])
        patch_delivery_line_actual(lines[0]["id"], loc["id"], 7)
        resolved = resolve_delivery_dispute(delv["id"])
        # Client credit = 300 after resolution.
        client_after = validate_success(api.get_client(client["id"], TEST_USERS["platform_admin_headers"]))
        assert client_after["credit_balance_cents"] == resolved["dispute_credit_cents"] == 300, (
            f"client credit ({client_after['credit_balance_cents']}) must equal "
            f"delivery credit ({resolved['dispute_credit_cents']}) = 300"
        )


class TestTimeConservationCumulativeActiveDays:
    def test_cumulative_active_days_increments_only_on_exit_from_active(self, api):
        """PRD §3.3: "Pause flips status to PAUSED, server-stamps paused_at to the current
        clock, and increments cumulative_active_days by the whole number of days between
        the subscription's most recent ACTIVE entry and the current clock — a fractional
        partial day is dropped (the increment is computed by taking the elapsed time and
        flooring it to whole days)."
        PRD §3.3: "It is incremented only on transitions out of ACTIVE (that is, at
        pause and at cancel-from-active), never mid-ACTIVE."

        Design: Difficulty/compensating_invariant/time_conservation_cumulative_active_days
        """
        state = setup_active_subscription(clock="2026-06-01T00:00:00Z")
        sub = state["subscription"]
        client = state["client"]
        assert sub["cumulative_active_days"] == 0, \
            f"at activate: cumulative should be 0; got {sub['cumulative_active_days']}"
        # Advance 10 days, then pause -> +10 days.
        set_clock("2026-06-11T00:00:00Z")
        paused = pause_subscription(sub["id"], client["id"])
        assert paused["cumulative_active_days"] == 10, \
            f"after 10-day pause: expected 10; got {paused['cumulative_active_days']}"

    def test_multiple_pause_resume_cycles_sum_active_segments(self, api):
        """PRD §3.3: "The active subscription's cumulative_active_days tracks the total
        whole logical days the subscription has spent in ACTIVE across all pause/resume
        loops. It is incremented only on transitions out of ACTIVE."

        Design: Difficulty/compensating_invariant/time_conservation_cumulative_active_days
        """
        state = setup_active_subscription(clock="2026-06-01T00:00:00Z")
        sub = state["subscription"]
        client = state["client"]
        # Day 0..10: ACTIVE; pause on day 10 -> +10.
        set_clock("2026-06-11T00:00:00Z")
        paused1 = pause_subscription(sub["id"], client["id"])
        assert paused1["cumulative_active_days"] == 10

        # Day 10..15: PAUSED; resume on day 15.
        set_clock("2026-06-16T00:00:00Z")
        resume_subscription(sub["id"], client["id"])
        # Day 15..20: ACTIVE; pause on day 20 -> +5.
        set_clock("2026-06-21T00:00:00Z")
        paused2 = pause_subscription(sub["id"], client["id"])
        assert paused2["cumulative_active_days"] == 15, \
            f"two active segments (10+5) should sum to 15; got {paused2['cumulative_active_days']}"


# ─────────────────────────────────────────────────────────────
# Corner/cross_cutting_layers
# ─────────────────────────────────────────────────────────────

def test_subscription_create_with_stale_client_version_returns_412(api):
    """PRD §2.8: "If expected_client_version does not equal the client's current version,
    the request is rejected with ERR_STALE_CLIENT_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_layers/subscription_create_stale_client_version_412
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(tier="OCC-1", billing_type="FLAT", flat_fee_cents=1000,
                      volume_discount_threshold_headcount=10)
    client = create_client(name="OccCo-OCC", headcount=5)
    # Bump version via PATCH.
    patched = validate_success(api.patch_client_headcount(
        client["id"], {"headcount": 7}, TEST_USERS["platform_admin_headers"],
    ))
    current_version = patched["version"]
    # Attempt create with stale (current-1).
    res = api.create_subscription(
        client["id"],
        {"plan_id": plan["id"], "expected_client_version": current_version - 1},
        make_client_admin_headers(client["id"]),
    )
    validate_error(res, "ERR_STALE_CLIENT_VERSION", expected_status=412)


def test_client_version_increments_by_one_per_patch(api):
    """PRD §2.4: "version (integer): a monotonically increasing counter that begins at 1
    on creation and increments by one on every mutation of the resource's fields."

    Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
    """
    r0 = validate_success(api.create_client(
        {"name": "V-INC", "headcount": 5}, TEST_USERS["platform_admin_headers"],
    ), expected_status=201)
    assert r0["version"] == 1, f"created client should start at version=1; got {r0['version']}"

    r1 = validate_success(api.patch_client_headcount(
        r0["id"], {"headcount": 6}, TEST_USERS["platform_admin_headers"],
    ))
    assert r1["version"] == 2, f"after first patch: expected version=2; got {r1['version']}"

    r2 = validate_success(api.patch_client_headcount(
        r0["id"], {"headcount": 7}, TEST_USERS["platform_admin_headers"],
    ))
    assert r2["version"] == 3, f"after second patch: expected version=3; got {r2['version']}"


def test_overdue_invoice_default_sweep_flips_unpaid_to_default(api):
    """PRD §3.7: "A platform admin can drive the logical clock forward for test scenarios
    ... and then invoke an admin-only sweep that walks every invoice, and for each invoice
    whose payment_status is UNPAID and whose current clock is at least 30 days past
    period_end, flips payment_status from UNPAID to DEFAULT."

    Design: Corner/cross_cutting_layers/overdue_invoice_default_sweep
    """
    state = setup_active_subscription(
        clock="2026-06-01T00:00:00Z",
        plan_overrides={"tier": "DF-1", "billing_type": "FLAT", "flat_fee_cents": 1000,
                        "volume_discount_threshold_headcount": 10},
    )
    state = close_and_get_invoice(state, close_clock="2026-07-05T00:00:00Z")
    inv = state["invoice"]
    assert inv["payment_status"] == "UNPAID"
    # Invoice period_end = 2026-07-01 (RC.effective_to). +30 days => 2026-07-31 onward triggers default.
    set_clock("2026-09-01T00:00:00Z")
    validate_success(api.advance_invoice_default(TEST_USERS["platform_admin_headers"]))
    got = validate_success(api.get_invoice(inv["id"], TEST_USERS["platform_admin_headers"]))
    assert got["payment_status"] == "DEFAULT", \
        f"overdue sweep must flip UNPAID -> DEFAULT; got {got['payment_status']!r}"
