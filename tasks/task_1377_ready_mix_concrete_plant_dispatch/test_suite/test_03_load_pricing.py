"""Final-charge pricing: escalation index selection, provisional vs final
variants, wait-time boundaries and cap, short-load boundary, and the Saturday
surcharge composition."""
import pytest

from test_helpers import (
    TEST_USERS,
    get_invoice_for_order,
    get_load,
    get_order,
    schedule_load,
    schedule_load_fresh,
    set_clock,
    setup_completed_load,
    setup_confirmed_order,
    validate_success,
    batch_load,
)

DISP = TEST_USERS["dispatcher_headers"]
DRV1 = TEST_USERS["driver_headers"]
DRV2 = TEST_USERS["driver2_headers"]


class TestProvisionalVsFinalVariant:
    def test_confirm_month_index_pins_provisional_quote(self, api):
        """PRD §3.3: "Confirmation also computes the provisional quote — the
        PROVISIONAL variant of the per-load final charge calculation. The
        escalated base is computed as in §3.2 except that the index month is
        the greatest `effective_month` on or before the month of the
        confirmation date. The concrete line uses the ordered `qty_yd3` rather
        than any discharged quantity; the wait line and the short-load line are
        both zero at this stage; the Saturday surcharge still applies when the
        `pour_date` falls on a Saturday, computed on the concrete line alone
        (there is no short-load line to include)."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_load_pricing
        """
        set_clock("2026-07-15T09:00:00Z")
        ctx = setup_confirmed_order(indices=[("2026-06", 100.0), ("2026-07", 110.0)])
        order = get_order(ctx["order"]["id"])
        # Confirm month 2026-07 -> index 110.0 -> escalated base 15000*1.1.
        assert order["escalated_base_cents"] == 16500
        # 8.0 * 16500 = 132000 concrete + 13200 Saturday = 145200.
        assert order["provisional_total_cents"] == 145200

    def test_final_variant_uses_pour_month_index_and_actual_wait(self, api):
        """PRD §3.7: "Completion then runs the FINAL variant of the per-load
        charge calculation, in this pinned order. The escalated base
        `escalated_base_cents` is recomputed from the pinned price list and the
        pour month's index (§3.2). The concrete line `concrete_cents` is
        `discharged_qty_yd3` multiplied by that escalated base, rounded half-up
        to the whole cent."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_load_pricing
        """
        set_clock("2026-07-15T09:00:00Z")
        ctx = setup_confirmed_order(indices=[("2026-06", 100.0), ("2026-07", 110.0)])
        order = get_order(ctx["order"]["id"])
        assert order["provisional_total_cents"] == 145200

        # Publish the pour-month index only after the order was confirmed.
        from test_helpers import publish_index

        publish_index(ctx["plant"]["id"], "2026-08", 115.0)
        load = schedule_load(
            order["id"], order["version"],
            qty_yd3=8.0, truck_id=ctx["trucks"]["T1"]["id"],
        )
        batch_load(load["id"], "2026-08-15T10:00:00Z")
        validate_success(api.depart_load(load["id"], DRV1), 200)
        set_clock("2026-08-15T10:30:00Z")
        validate_success(api.arrive_load(load["id"], DRV1), 200)
        validate_success(api.start_pour_load(load["id"], DRV1), 200)
        set_clock("2026-08-15T12:00:00Z")
        completed = validate_success(
            api.complete_load(load["id"], {"discharged_qty_yd3": 8.0}, DRV1), 200
        )
        # Pour month 2026-08 -> index 115.0 -> escalated base 17250.
        assert completed["concrete_cents"] == 138000
        # 138000 concrete + 7500 wait (90-60=30 min x 250) + 13800 Saturday.
        assert completed["final_charge_cents"] == 159300
        assert order["provisional_total_cents"] != completed["final_charge_cents"]


class TestSaturdayWaitShortLoadInteraction:
    def test_surcharge_base_excludes_wait_fee(self, api):
        """PRD §3.7: "The Saturday line `saturday_fee_cents` applies only when
        the order's `pour_date` falls on a Saturday: it is the sum of the
        concrete line and the short-load line, multiplied by
        `saturday_surcharge_pct`, rounded half-up to the whole cent — the wait
        fee is deliberately excluded from the surcharge base."

        Design: Difficulty/combinatorial_formula/saturday_wait_shortload_conditional_interaction
        """
        ctx, load = setup_completed_load(indices=[("2026-08", 115.0)])
        assert load["on_site_minutes"] == 90
        assert load["concrete_cents"] == 138000
        assert load["short_load_fee_cents"] == 0
        assert load["wait_fee_cents"] == 7500  # (90 - 60) * 250, under the cap
        # 10% of (138000 + 0) = 13800; surcharging the wait fee would give 14550.
        assert load["saturday_fee_cents"] == 13800

    def test_final_charge_is_sum_of_four_rounded_lines(self, api):
        """PRD §3.7: "The load's `final_charge_cents` is the sum of the four
        lines, each already individually rounded — round per line, then sum."

        Design: Difficulty/combinatorial_formula/saturday_wait_shortload_conditional_interaction
        """
        ctx, load = setup_completed_load(indices=[("2026-08", 115.0)])
        assert load["final_charge_cents"] == (
            load["concrete_cents"]
            + load["short_load_fee_cents"]
            + load["wait_fee_cents"]
            + load["saturday_fee_cents"]
        )
        assert load["final_charge_cents"] == 159300


class TestWaitFeeBoundaries:
    def _build_two_load_order(self, api):
        """One 16.0 yd3 Monday order with two 8.0 yd3 loads, both batched and
        departed; arrival/complete clocks steered per load."""
        ctx = setup_confirmed_order(
            indices=[("2026-08", 115.0)],
            order_overrides={
                "qty_yd3": 16.0,
                "pour_date": "2026-08-17",
                "pour_window_start": "07:00",
                "pour_window_end": "12:00",
            },
            truck_fleet_numbers=("T1", "T2"),
        )
        l1 = schedule_load(
            ctx["order"]["id"], ctx["order_version"],
            qty_yd3=8.0, truck_id=ctx["trucks"]["T1"]["id"],
        )
        l2 = schedule_load_fresh(
            ctx["order"]["id"], qty_yd3=8.0, truck_id=ctx["trucks"]["T2"]["id"]
        )
        batch_load(l1["id"], "2026-08-17T09:00:00Z")
        batch_load(l2["id"], "2026-08-17T09:30:00Z")
        validate_success(api.depart_load(l1["id"], DRV1), 200)
        validate_success(api.depart_load(l2["id"], DRV2), 200)
        return ctx, l1, l2

    def test_exactly_free_minutes_pays_zero_and_next_minute_bills(self, api):
        """PRD §3.7: "The billable wait is the greater of zero and
        `on_site_minutes` minus `wait_free_minutes`; the wait line
        `wait_fee_cents` is that billable wait multiplied by
        `wait_rate_per_minute_cents`, capped at `wait_fee_cap_cents` — the
        smaller of the two values is charged."

        Design: Difficulty/boundary_precision_check/wait_fee_exact_free_minutes_boundary
        """
        ctx, l1, l2 = self._build_two_load_order(api)
        # L1: exactly 60 on-site minutes -> free.
        set_clock("2026-08-17T09:30:00Z")
        validate_success(api.arrive_load(l1["id"], DRV1), 200)
        set_clock("2026-08-17T10:00:00Z")
        validate_success(api.arrive_load(l2["id"], DRV2), 200)
        set_clock("2026-08-17T10:30:00Z")
        validate_success(
            api.complete_load(l1["id"], {"discharged_qty_yd3": 8.0}, DRV1), 200
        )
        # L2: 61 on-site minutes -> one billable minute.
        set_clock("2026-08-17T11:01:00Z")
        validate_success(
            api.complete_load(l2["id"], {"discharged_qty_yd3": 8.0}, DRV2), 200
        )

        l1_after = get_load(l1["id"])
        l2_after = get_load(l2["id"])
        assert l1_after["on_site_minutes"] == 60
        assert l1_after["wait_fee_cents"] == 0, "equality with free minutes is free"
        assert l2_after["on_site_minutes"] == 61
        assert l2_after["wait_fee_cents"] == 250, "first billable minute at 250/min"
        # Monday: no Saturday surcharge; concrete is 8 * 17250 = 138000 each.
        assert l1_after["final_charge_cents"] == 138000
        assert l2_after["final_charge_cents"] == 138250

    def test_below_free_minutes_pays_zero(self, api):
        """PRD §3.7: "The billable wait is the greater of zero and
        `on_site_minutes` minus `wait_free_minutes`; the wait line
        `wait_fee_cents` is that billable wait multiplied by
        `wait_rate_per_minute_cents`, capped at `wait_fee_cap_cents` — the
        smaller of the two values is charged."

        Design: Difficulty/boundary_precision_check/wait_fee_exact_free_minutes_boundary
        """
        # 59 on-site minutes: max(0, 59 - 60) = 0 billable.
        ctx, load = setup_completed_load(
            indices=[("2026-08", 115.0)],
            order_overrides={
                "qty_yd3": 8.0,
                "pour_date": "2026-08-17",
                "pour_window_start": "07:00",
                "pour_window_end": "12:00",
            },
            batch_time="2026-08-17T09:00:00Z",
            arrive_at="2026-08-17T09:30:00Z",
            complete_at="2026-08-17T10:29:00Z",
            start_pour=False,
        )
        assert load["on_site_minutes"] == 59
        assert load["wait_fee_cents"] == 0
        assert load["final_charge_cents"] == 138000, (
            "Monday pour, no short load, zero wait -> concrete line only"
        )

    def test_wait_fee_capped_at_cap(self, api):
        """PRD §3.7: "the wait line `wait_fee_cents` is that billable wait
        multiplied by `wait_rate_per_minute_cents`, capped at
        `wait_fee_cap_cents` — the smaller of the two values is charged."

        Design: Corner/calculations/wait_fee_cap_boundary
        """
        ctx, load = setup_completed_load(
            indices=[("2026-08", 115.0)],
            order_overrides={"pour_window_start": "07:00", "pour_window_end": "14:00"},
            arrive_at="2026-08-15T10:30:00Z",
            complete_at="2026-08-15T13:30:00Z",
            start_pour=False,
        )
        assert load["on_site_minutes"] == 180
        # Uncapped: (180 - 60) * 250 = 30000; capped at 15000.
        assert load["wait_fee_cents"] == 15000
        # Saturday pour: 138000 + 0 short + 15000 wait + 13800 surcharge.
        assert load["final_charge_cents"] == 166800


class TestShortLoadBoundary:
    def test_exact_min_load_pays_no_fee_but_below_pays(self, api):
        """PRD §3.7: "The short-load line `short_load_fee_cents` is the price
        list's flat fee when `discharged_qty_yd3` is strictly below
        `min_load_yd3`, and zero otherwise."

        Design: Corner/calculations/short_load_exactly_min_load_no_fee
        """
        ctx = setup_confirmed_order(
            indices=[("2026-08", 115.0)],
            order_overrides={
                "qty_yd3": 7.0,
                "pour_date": "2026-08-17",
                "pour_window_start": "07:00",
                "pour_window_end": "12:00",
            },
            truck_fleet_numbers=("T1", "T2"),
        )
        l1 = schedule_load(
            ctx["order"]["id"], ctx["order_version"],
            qty_yd3=4.0, truck_id=ctx["trucks"]["T1"]["id"],
        )
        l2 = schedule_load_fresh(
            ctx["order"]["id"], qty_yd3=3.0, truck_id=ctx["trucks"]["T2"]["id"]
        )
        batch_load(l1["id"], "2026-08-17T09:00:00Z")
        batch_load(l2["id"], "2026-08-17T09:30:00Z")
        validate_success(api.depart_load(l1["id"], DRV1), 200)
        validate_success(api.depart_load(l2["id"], DRV2), 200)
        set_clock("2026-08-17T09:30:00Z")
        validate_success(api.arrive_load(l1["id"], DRV1), 200)
        set_clock("2026-08-17T10:00:00Z")
        validate_success(
            api.complete_load(l1["id"], {"discharged_qty_yd3": 4.0}, DRV1), 200
        )
        validate_success(api.arrive_load(l2["id"], DRV2), 200)
        set_clock("2026-08-17T10:30:00Z")
        validate_success(
            api.complete_load(l2["id"], {"discharged_qty_yd3": 3.0}, DRV2), 200
        )

        l1_after = get_load(l1["id"])
        l2_after = get_load(l2["id"])
        assert l1_after["short_load_fee_cents"] == 0, (
            "4.0 == min_load: strict < does not trigger the fee"
        )
        assert l1_after["final_charge_cents"] == 69000  # 4 * 17250
        assert l2_after["short_load_fee_cents"] == 7500
        assert l2_after["final_charge_cents"] == 59250  # 3 * 17250 + 7500

        invoice = get_invoice_for_order(ctx["order"]["id"])
        assert invoice["total_cents"] == 128250
        order = get_order(ctx["order"]["id"])
        assert order["delivery_status"] == "DELIVERED", "7.0 >= 7.0 completes"


class TestEscalationIndexSelection:
    def test_fallback_ratio_one_when_no_index_published(self, api):
        """PRD §3.2: "If no such row has been published, the escalation base
        itself stands in, making the ratio exactly 1.0."

        Design: Corner/calculations/escalation_fallback_ratio_one_when_no_index
        """
        ctx, load = setup_completed_load(
            indices=None,
            order_overrides={
                "pour_date": "2026-08-17",
                "pour_window_start": "07:00",
                "pour_window_end": "10:00",
            },
            batch_time="2026-08-17T09:00:00Z",
            arrive_at="2026-08-17T09:30:00Z",
            complete_at="2026-08-17T10:00:00Z",
            start_pour=False,
        )
        order = get_order(ctx["order"]["id"])
        assert order["escalated_base_cents"] == 15000, "fallback ratio exactly 1.0"
        assert load["concrete_cents"] == 120000  # 8 * 15000
        assert load["final_charge_cents"] == 120000, (
            "Monday, 30 free wait minutes, no short load -> concrete line only"
        )

    def test_latest_index_on_or_before_target_month(self, api):
        """PRD §3.2: "Escalation selects an index chronologically. For an
        order with a given `pour_date`, the applicable index is the
        `index_points` of the plant's index row with the greatest
        `effective_month` that is on or before the pour month."

        Design: Corner/calculations/index_selection_latest_leq_pour_month
        """
        set_clock("2026-07-10T09:00:00Z")
        # Only 2026-06 and 2026-08 are published: the July confirm must fall
        # back to the June row; the August pour uses the August row.
        ctx = setup_confirmed_order(indices=[("2026-06", 100.0), ("2026-08", 115.0)])
        order = get_order(ctx["order"]["id"])
        assert order["escalated_base_cents"] == 15000, (
            "greatest effective_month <= 2026-07 is 2026-06 at 100.0 -> ratio 1.0"
        )
        # Provisional: 8 * 15000 = 120000 concrete + 12000 Saturday = 132000.
        assert order["provisional_total_cents"] == 132000

        load = schedule_load(
            order["id"], order["version"],
            qty_yd3=8.0, truck_id=ctx["trucks"]["T1"]["id"],
        )
        batch_load(load["id"], "2026-08-15T10:00:00Z")
        validate_success(api.depart_load(load["id"], DRV1), 200)
        set_clock("2026-08-15T10:30:00Z")
        validate_success(api.arrive_load(load["id"], DRV1), 200)
        set_clock("2026-08-15T11:00:00Z")
        completed = validate_success(
            api.complete_load(load["id"], {"discharged_qty_yd3": 8.0}, DRV1), 200
        )
        assert completed["concrete_cents"] == 138000, (
            "pour month 2026-08 selects the 115.0 row -> escalated base 17250"
        )
        # 138000 + 0 wait (30 free minutes) + 13800 Saturday = 151800.
        assert completed["final_charge_cents"] == 151800
