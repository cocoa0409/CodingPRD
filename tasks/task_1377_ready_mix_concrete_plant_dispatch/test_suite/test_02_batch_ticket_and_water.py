"""Batch ticket dosing, actual w/c ratio recomputation, water additions, and
the over-watering cascade onto strength liability and cylinder acceptance
basis."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_water_addition,
    batch_load,
    get_cylinder_set,
    get_load,
    get_truck,
    schedule_load,
    schedule_load_fresh,
    set_clock,
    setup_batched_load,
    setup_confirmed_order,
    setup_pouring_load,
    setup_cylinder_set_on_pouring_load,
    validate_error,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]
BATCH_OP = TEST_USERS["batch_operator_headers"]
DRV1 = TEST_USERS["driver_headers"]


class TestAdmixtureRoundPerLineThenSum:
    """Pinned round-per-line-then-sum dosing on the batch ticket."""

    def test_per_line_doses_and_total_rounded_per_line(self, api):
        """PRD §3.5: "Each admixture line of the mix is dosed individually: the
        line's `dose_oz_per_cwt` multiplied by `cement_lb` and divided by 100,
        rounded half-up to 0.1 ounce, producing the ticket's `admixture_doses`
        entries. The ticket's `total_admixture_oz` is the sum of those per-line
        rounded doses — round per line first, then sum."

        Design: Difficulty/combinatorial_formula/admixture_round_per_line_then_sum
        """
        ctx, load = setup_batched_load(
            order_overrides={
                "qty_yd3": 6.0,
                "pour_date": "2026-08-17",
                "pour_window_start": "07:00",
                "pour_window_end": "10:00",
            },
            load_qty=6.0,
            batch_time="2026-08-17T09:00:00Z",
        )
        res = api.get_batch_ticket(load["id"], BATCH_OP)
        tickets = validate_success(res, 200)
        assert len(tickets) == 1
        ticket = tickets[0]
        assert ticket["cement_lb"] == 3384  # 564 * 6.0
        assert ticket["batch_water_lb"] == 1523  # round_half_up(0.45 * 3384)
        doses = {d["admixture_code"]: d["dose_oz"] for d in ticket["admixture_doses"]}
        assert doses["AEA"] == pytest.approx(52.5, abs=1e-9)  # 1.55*3384/100 -> 52.452
        assert doses["WR"] == pytest.approx(89.7, abs=1e-9)  # 2.65*3384/100 -> 89.676
        # 52.5 + 89.7 = 142.2; sum-then-round of raw doses would give 142.1.
        assert ticket["total_admixture_oz"] == pytest.approx(142.2, abs=1e-9)

    def test_total_is_not_sum_then_round(self, api):
        """PRD §3.5: "The ticket's `total_admixture_oz` is the sum of those
        per-line rounded doses — round per line first, then sum. Summing the
        raw doses and rounding once at the end is explicitly the wrong order
        and yields different totals."

        Design: Difficulty/combinatorial_formula/admixture_round_per_line_then_sum
        """
        ctx, load = setup_batched_load(
            order_overrides={
                "qty_yd3": 6.0,
                "pour_date": "2026-08-17",
                "pour_window_start": "07:00",
                "pour_window_end": "10:00",
            },
            load_qty=6.0,
            batch_time="2026-08-17T09:00:00Z",
        )
        tickets = validate_success(api.get_batch_ticket(load["id"], BATCH_OP), 200)
        ticket = tickets[0]
        per_line_sum = sum(d["dose_oz"] for d in ticket["admixture_doses"])
        assert ticket["total_admixture_oz"] == pytest.approx(per_line_sum, abs=1e-9)
        assert ticket["total_admixture_oz"] == pytest.approx(142.2, abs=1e-9)
        assert ticket["total_admixture_oz"] != pytest.approx(142.1, abs=1e-9), (
            "142.1 is the explicitly-wrong sum-then-round result"
        )


class TestBatchSideEffects:
    def test_batch_creates_ticket_flips_truck_and_starts_order(self, api):
        """PRD §3.5: "On success the batch ticket is created — one ticket per
        load, 1:1, its `load_id` pointing back at the load — and the ticket's
        `ticket_number` is sequential per plant: the count of existing tickets
        for that plant plus one."
        PRD §3.5: "Batching stamps the load's `batch_time`, computes the load's
        initial `actual_wc_ratio` from the batch water alone (see §3.6), and
        flips the truck `AVAILABLE → ON_DELIVERY`. If this is the order's first
        load to reach `BATCHED`, the order automatically moves `SCHEDULED →
        IN_PROGRESS`."

        Design: Corner/state_machines/batch_creates_ticket_and_flips_truck
        """
        ctx = setup_confirmed_order()
        load = schedule_load(
            ctx["order"]["id"], ctx["order_version"],
            qty_yd3=8.0, truck_id=ctx["trucks"]["T1"]["id"],
        )
        batched = batch_load(load["id"], "2026-08-15T10:00:00Z")
        assert batched["status"] == "BATCHED"
        assert batched["actual_wc_ratio"] == pytest.approx(0.45, abs=1e-9), (
            "initial ratio is computed from batch water alone: 2030/4512 -> 0.450"
        )

        tickets = validate_success(api.get_batch_ticket(load["id"], BATCH_OP), 200)
        assert len(tickets) == 1
        ticket = tickets[0]
        assert ticket["ticket_number"] == 1
        assert ticket["load_id"] == load["id"]
        assert ticket["cement_lb"] == 4512  # 564 * 8.0
        assert ticket["batch_water_lb"] == 2030  # round_half_up(0.45 * 4512)
        assert ticket["total_admixture_oz"] == pytest.approx(189.5, abs=1e-9)

        truck = get_truck(ctx["trucks"]["T1"]["id"])
        assert truck["status"] == "ON_DELIVERY"

        from test_helpers import get_order

        order = get_order(ctx["order"]["id"])
        assert order["delivery_status"] == "IN_PROGRESS"

    def test_batch_ticket_numbers_sequential_per_plant(self, api):
        """PRD §3.5: "the ticket's `ticket_number` is sequential per plant:
        the count of existing tickets for that plant plus one."

        Design: Corner/endpoints/batch_ticket_sequential_numbering_per_plant
        """
        ctx = setup_confirmed_order(
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

        t1 = validate_success(api.get_batch_ticket(l1["id"], BATCH_OP), 200)
        t2 = validate_success(api.get_batch_ticket(l2["id"], BATCH_OP), 200)
        assert t1[0]["ticket_number"] == 1
        assert t2[0]["ticket_number"] == 2


class TestWaterAdditions:
    def test_water_addition_append_only_shape_and_ratio_recompute(self, api):
        """PRD §2.4: "Water additions are also append-only records; they carry
        `added_at` as their logical-clock timestamp."
        PRD §3.6: "Each addition carries the `gallons` added and a
        `customer_authorized` flag, and the server stamps `added_by_user_id`
        from the driver's `X-User-ID` and `added_at` from the logical clock.
        Every addition recomputes the load's `actual_wc_ratio`: the total water
        is the batch ticket's `batch_water_lb` plus 8.34 times the sum of
        `gallons` across all of the load's water additions, and the ratio is
        that total divided by the ticket's `cement_lb`, rounded half-up to 3
        decimal places."

        Design: Corner/entities/water_addition_immutable_event_shape
        """
        ctx, load = setup_pouring_load()
        res = api.add_water(
            load["id"], {"gallons": 20, "customer_authorized": True}, DRV1
        )
        addition = validate_success(res, 201)
        assert_water_addition(addition)
        assert addition["added_by_user_id"] == "drv-1"
        assert addition["added_at"].startswith("2026-08-15T10:30:00")

        after = get_load(load["id"])
        # (2030 + 8.34*20) / 4512 = 0.48688... -> 0.487 rounded half-up to 3dp.
        assert after["actual_wc_ratio"] == pytest.approx(0.487, abs=1e-9)
        assert after["over_watered"] is False

    def test_rounded_ceiling_equality_is_not_over_watered(self, api):
        """PRD §3.6: "The load's `over_watered` flag becomes true if and only
        if this rounded 3-decimal ratio is strictly greater than the mix's
        `max_wc_ratio` — a ratio that rounds to exactly the ceiling is not
        over-watered."

        Design: Corner/calculations/wc_ratio_rounded_equality_not_over_watered
        """
        ctx, load = setup_pouring_load()
        api.add_water(load["id"], {"gallons": 27, "customer_authorized": True}, DRV1)
        after_27 = get_load(load["id"])
        # (2030 + 8.34*27) / 4512 = 0.49978... -> 0.500 == ceiling: not over.
        assert after_27["actual_wc_ratio"] == pytest.approx(0.5, abs=1e-9)
        assert after_27["over_watered"] is False

        api.add_water(load["id"], {"gallons": 1, "customer_authorized": True}, DRV1)
        after_28 = get_load(load["id"])
        # (2030 + 8.34*28) / 4512 = 0.50163... -> 0.502 > 0.50: over.
        assert after_28["actual_wc_ratio"] == pytest.approx(0.502, abs=1e-9)
        assert after_28["over_watered"] is True
        assert after_28["strength_liability"] == "CUSTOMER", (
            "a customer-authorized addition flipped the load over the ceiling"
        )

    def test_water_additions_listed_in_added_at_order(self, api):
        """PRD §2.3: "Results are sorted by `created_at` ascending."
        PRD §3.6: "Every addition recomputes the load's `actual_wc_ratio`: the
        total water is the batch ticket's `batch_water_lb` plus 8.34 times the
        sum of `gallons` across all of the load's water additions, and the
        ratio is that total divided by the ticket's `cement_lb`, rounded
        half-up to 3 decimal places."

        Design: Corner/endpoints/water_additions_subresource_listing
        """
        ctx, load = setup_pouring_load()
        first = validate_success(
            api.add_water(
                load["id"], {"gallons": 5, "customer_authorized": False}, DRV1
            ),
            201,
        )
        set_clock("2026-08-15T10:45:00Z")
        second = validate_success(
            api.add_water(
                load["id"], {"gallons": 10, "customer_authorized": True}, DRV1
            ),
            201,
        )

        rows = validate_success(api.list_water_additions(load["id"], DISP), 200)
        assert len(rows) == 2
        assert rows[0]["id"] == first["id"]
        assert rows[1]["id"] == second["id"]
        assert rows[0]["gallons"] == pytest.approx(5)
        assert rows[1]["gallons"] == pytest.approx(10)
        assert rows[1]["customer_authorized"] is True
        assert rows[1]["added_by_user_id"] == "drv-1"

        after = get_load(load["id"])
        # (2030 + 8.34*15) / 4512 = 0.47784... -> 0.478.
        assert after["actual_wc_ratio"] == pytest.approx(0.478, abs=1e-9)
        assert after["over_watered"] is False


class TestOverWateredCascade:
    def test_flip_sets_liability_customer_and_rebases_cylinder_sets(self, api):
        """PRD §3.6: "The moment `over_watered` flips to true, two cascades
        fire. The load's `strength_liability` is set: it becomes `CUSTOMER` if
        any water addition on the load has `customer_authorized` set to true,
        and `PLANT` otherwise. And every non-terminal cylinder set cast from
        that load has its `acceptance_basis` flipped from `DESIGN_BASIS` to
        `AS_PLACED`."

        Design: Difficulty/transitive_cascade/water_addition_flips_cylinder_basis_chain
        """
        ctx, load, cset = setup_cylinder_set_on_pouring_load()
        assert cset["acceptance_basis"] == "DESIGN_BASIS"

        validate_success(
            api.add_water(
                load["id"], {"gallons": 60, "customer_authorized": True}, DRV1
            ),
            201,
        )
        after = get_load(load["id"])
        # (2030 + 8.34*60) / 4512 = 0.56090... -> 0.561 > 0.50.
        assert after["actual_wc_ratio"] == pytest.approx(0.561, abs=1e-9)
        assert after["over_watered"] is True
        assert after["strength_liability"] == "CUSTOMER"

        cset_after = get_cylinder_set(cset["id"])
        assert cset_after["acceptance_basis"] == "AS_PLACED"

    def test_unauthorized_over_watering_sets_liability_plant(self, api):
        """PRD §3.6: "The load's `strength_liability` is set: it becomes
        `CUSTOMER` if any water addition on the load has `customer_authorized`
        set to true, and `PLANT` otherwise."

        Design: Difficulty/transitive_cascade/water_addition_flips_cylinder_basis_chain
        """
        ctx, load, cset = setup_cylinder_set_on_pouring_load()
        validate_success(
            api.add_water(
                load["id"], {"gallons": 60, "customer_authorized": False}, DRV1
            ),
            201,
        )
        after = get_load(load["id"])
        assert after["actual_wc_ratio"] == pytest.approx(0.561, abs=1e-9)
        assert after["over_watered"] is True
        assert after["strength_liability"] == "PLANT", (
            "no customer-authorized addition on the load -> PLANT carries it"
        )
        cset_after = get_cylinder_set(cset["id"])
        assert cset_after["acceptance_basis"] == "AS_PLACED"


class TestLoadCreationState:
    def test_new_load_scheduled_with_clean_counters(self, api):
        """PRD §3.4: "The first successful schedule on an order moves the
        order `CONFIRMED → SCHEDULED` automatically."
        PRD §3.4: "The load's `order_id` comes from the scheduling path, and
        its `plant_id` is denormalized from the order's plant at schedule
        time."
        PRD §3.6: "The load's `strength_liability` starts at `NONE` and is
        otherwise only set by a flagged certification (§3.8)."

        Design: Corner/state_machines/load_initial_state_scheduled
        """
        ctx = setup_confirmed_order()
        load = schedule_load(
            ctx["order"]["id"], ctx["order_version"],
            qty_yd3=8.0, truck_id=ctx["trucks"]["T1"]["id"],
        )
        assert load["status"] == "SCHEDULED"
        assert load["discharged_qty_yd3"] == 0
        assert load["over_watered"] is False
        assert load["strength_liability"] == "NONE"
        assert load["order_id"] == ctx["order"]["id"]
        assert load["plant_id"] == ctx["plant"]["id"]

        from test_helpers import get_order

        order = get_order(ctx["order"]["id"])
        assert order["delivery_status"] == "SCHEDULED", (
            "first successful schedule moves the order CONFIRMED -> SCHEDULED"
        )
