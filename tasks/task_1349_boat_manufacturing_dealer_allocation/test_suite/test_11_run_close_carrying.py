"""The season checkpoint: run close accrues carrying costs in two variants,
releases slots, and auto-cancels ALLOCATED orders (PRD §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_production_run,
    book_order_no_options,
    certify_hull,
    confirm_order,
    create_dealer_order_payload,
    create_hull,
    create_slot,
    deliver_hull,
    get_hull,
    get_order,
    get_run,
    get_slot,
    make_dealer_principal_headers,
    set_clock,
    setup_bookable_world,
    setup_committed_hull,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["production_planner_headers"]


class TestCarryingDualVariant:
    def test_carrying_actual_vs_season_weighted_peak(self, api):
        """PRD §3.3: "the system counts the whole days from the hull's
        `completed_at` to the clock (zero when completion and close share a
        day), computes the actual carrying cost as those days times 750 cents
        per day, and computes the season-weighted cost as the actual cost times
        the season factor — 1.25 for `PEAK`, 1.00 for `SHOULDER`, 0.60 for
        `OFF_PEAK` — rounded half up."
        PRD §3.3: "The run's `total_carrying_actual_cents` records the sum of
        the unweighted actual costs (the planning and statement view), its
        `total_carrying_seasonal_cents` the sum of the weighted costs, and each
        hull's `carrying_cost_cents` accumulates the weighted amount — the
        season-weighted variant is the one persisted to the inventory-carrying
        ledger."

        One AT_PLANT hull completed at 2026-08-01, run closed at 2026-08-11:
        10 days -> 7500 actual; PEAK 1.25 -> 9375 weighted.

        Design: Difficulty/dual_variant_calc/carrying_cost_actual_vs_season_weighted
        """
        world = setup_committed_hull(api, option_set="tower_ballast", season="PEAK")
        # Hull completed at the startup clock 2026-08-01T00:00:00Z.
        set_clock(api, "2026-08-11T00:00:00Z")
        run = validate_success(api.close_production_run(world["run"]["id"], PLANNER), 200)
        assert_production_run(run)
        assert run["status"] == "CLOSED"
        assert run["total_carrying_actual_cents"] == 7500, (
            f"10 days x 750 = 7500 actual, got {run['total_carrying_actual_cents']}"
        )
        assert run["total_carrying_seasonal_cents"] == 9375, (
            f"rhu(7500 x 1.25 PEAK) = 9375, got {run['total_carrying_seasonal_cents']}"
        )
        hull = get_hull(api, world["hull"]["id"])
        assert hull["carrying_cost_cents"] == 9375, (
            "the season-weighted variant is the one persisted to the hull"
        )

    def test_carrying_actual_equals_seasonal_when_shoulder(self, api):
        """PRD §3.3: "computes the season-weighted cost as the actual cost
        times the season factor — 1.25 for `PEAK`, 1.00 for `SHOULDER`, 0.60
        for `OFF_PEAK` — rounded half up."

        SHOULDER's factor of 1.00 is the point where the two variants coincide:
        5 days -> 3750 both ways.

        Design: Difficulty/dual_variant_calc/carrying_cost_actual_vs_season_weighted
        """
        world = setup_committed_hull(api, with_options=False, season="SHOULDER")
        set_clock(api, "2026-08-06T00:00:00Z")  # five whole days after 08-01
        run = validate_success(api.close_production_run(world["run"]["id"], PLANNER), 200)
        assert run["total_carrying_actual_cents"] == 3750  # 5 x 750
        assert run["total_carrying_seasonal_cents"] == 3750, (
            "SHOULDER factor 1.00 keeps the weighted variant equal to actual"
        )
        hull = get_hull(api, world["hull"]["id"])
        assert hull["carrying_cost_cents"] == 3750

    def test_carrying_off_peak_variant_diverges_down(self, api):
        """PRD §3.3: "computes the season-weighted cost as the actual cost
        times the season factor — 1.25 for `PEAK`, 1.00 for `SHOULDER`, 0.60
        for `OFF_PEAK` — rounded half up."

        OFF_PEAK swings the divergence the other way: 10 days -> 7500 actual
        vs rhu(7500 x 0.60) = 4500 weighted.

        Design: Corner/cross_cutting_layers/dual_variant_carrying_actual_vs_seasonal_off_peak
        """
        world = setup_committed_hull(api, with_options=False, season="OFF_PEAK")
        set_clock(api, "2026-08-11T00:00:00Z")
        run = validate_success(api.close_production_run(world["run"]["id"], PLANNER), 200)
        assert run["total_carrying_actual_cents"] == 7500
        assert run["total_carrying_seasonal_cents"] == 4500
        hull = get_hull(api, world["hull"]["id"])
        assert hull["carrying_cost_cents"] == 4500, (
            "the season-weighted variant posts to the hull"
        )

    def test_carrying_empty_set_zero_totals(self, api):
        """PRD §3.3: "Delivered hulls are excluded; if no hull is still at the
        plant, both totals land at 0 and no error is raised."

        Design: Corner/calculations/carrying_cost_empty_set_zero_totals
        """
        world = setup_bookable_world(api, with_options=False)
        run = validate_success(api.close_production_run(world["run"]["id"], PLANNER), 200)
        assert run["status"] == "CLOSED"
        assert run["total_carrying_actual_cents"] == 0
        assert run["total_carrying_seasonal_cents"] == 0

    def test_carrying_delivered_hulls_excluded(self, api):
        """PRD §3.3: "First, carrying accrual: for every hull sitting on one of
        this run's slots whose `delivery_status` is still `AT_PLANT`, the
        system counts the whole days from the hull's `completed_at` to the clock
        (zero when completion and close share a day), computes the actual
        carrying cost as those days times 750 cents per day, and computes the
        season-weighted cost as the actual cost times the season factor — 1.25
        for `PEAK`, 1.00 for `SHOULDER`, 0.60 for `OFF_PEAK` — rounded half up."
        PRD §3.3: "Delivered hulls are excluded; if no hull is still at the
        plant, both totals land at 0 and no error is raised."

        Two hulls completed 2026-08-01; one delivered before close. Only the
        AT_PLANT hull accrues.

        Design: Corner/calculations/carrying_cost_delivered_hulls_excluded
        """
        world = setup_bookable_world(api, with_options=False,
                                     floor_plan_limit_cents=100000000)
        dealer, model, slot = world["dealer"], world["model"], world["slot"]
        hulls = []
        for _ in range(2):
            order = book_order_no_options(api, dealer, model, slot_id=slot["id"])
            order = confirm_order(api, order, dealer)
            hulls.append(create_hull(api, order["id"]))
        # Deliver the first hull (same day as completion); leave h2 AT_PLANT.
        certify_hull(api, hulls[0]["id"])
        deliver_hull(api, hulls[0]["id"])
        set_clock(api, "2026-08-11T00:00:00Z")
        run = validate_success(api.close_production_run(world["run"]["id"], PLANNER), 200)
        assert run["total_carrying_actual_cents"] == 7500, "only the AT_PLANT hull counts"
        assert run["total_carrying_seasonal_cents"] == 9375  # PEAK 1.25
        assert get_hull(api, hulls[0]["id"])["carrying_cost_cents"] == 0, (
            "DELIVERED hulls are excluded from accrual"
        )
        assert get_hull(api, hulls[1]["id"])["carrying_cost_cents"] == 9375


class TestRunCloseSideEffects:
    def test_close_auto_cancels_allocated_orders_waiving_fee(self, api):
        """PRD §3.3: "Third, every order still `ALLOCATED` on this run's slots
        is cancelled by the season rollover with `cancel_fee_cents` of 0 and a
        full refund of its deposit; unlike an ordinary cancellation, no
        waitlist promotion fires at close."

        Design: Corner/state_machines/run_close_auto_cancels_allocated_orders_waives_fee
        """
        world = setup_bookable_world(api, with_options=False)
        order = book_order_no_options(
            api, world["dealer"], world["model"], slot_id=world["slot"]["id"]
        )
        assert order["status"] == "ALLOCATED"
        validate_success(api.close_production_run(world["run"]["id"], PLANNER), 200)
        after = get_order(api, order["id"])
        assert after["status"] == "CANCELLED"
        assert after["cancel_fee_cents"] == 0, "season rollover waives the fee"
        assert after["refund_cents"] == 257500, "full deposit refund"

    def test_close_does_not_cancel_committed_orders(self, api):
        """PRD §3.3: "Fourth, `COMMITTED` orders on the run persist untouched
        and may still report production completion afterwards — hull creation
        deliberately does not require the run to be `OPEN`."

        Design: Corner/state_machines/run_close_does_not_cancel_committed_orders
        """
        world = setup_bookable_world(api, with_options=False)
        dealer, model, slot = world["dealer"], world["model"], world["slot"]
        o_allocated = book_order_no_options(api, dealer, model, slot_id=slot["id"])
        o_committed = book_order_no_options(api, dealer, model, slot_id=slot["id"])
        o_committed = confirm_order(api, o_committed, dealer)
        validate_success(api.close_production_run(world["run"]["id"], PLANNER), 200)
        assert get_order(api, o_allocated["id"])["status"] == "CANCELLED"
        assert get_order(api, o_committed["id"])["status"] == "COMMITTED", (
            "COMMITTED orders persist through the season close"
        )
        # The pinned exception: hull creation still works after close.
        hull = create_hull(api, o_committed["id"])
        assert hull["delivery_status"] == "AT_PLANT"

    def test_close_releases_slots_and_rejects_new_bookings(self, api):
        """PRD §3.3: "Second, every slot of the run transitions to `RELEASED` —
        a terminal state whose slots reject all new bookings — with each slot's
        `version` incremented."
        PRD §3.4: "With an explicit `slot_id`, the chosen slot's run must be
        `OPEN` and the slot itself `OPEN`, otherwise `ERR_RUN_NOT_OPEN`"

        Design: Corner/state_machines/build_slot_released_at_run_close_terminal
        """
        world = setup_bookable_world(api, with_options=False)
        validate_success(api.close_production_run(world["run"]["id"], PLANNER), 200)
        slot = get_slot(api, world["slot"]["id"])
        assert slot["status"] == "RELEASED"
        resp = api.create_dealer_order(
            create_dealer_order_payload(
                world["dealer"]["id"], world["model"]["id"],
                deposit_paid_cents=257500, slot_id=world["slot"]["id"],
            ),
            make_dealer_principal_headers(world["dealer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_OPEN)

    def test_close_checkpoint_recalculates_and_releases(self, api):
        """PRD §3.3: "Close performs four acts."
        PRD §3.3: "Second, every slot of the run transitions to `RELEASED` — a
        terminal state whose slots reject all new bookings — with each slot's
        `version` incremented."
        PRD §3.3: "Third, every order still `ALLOCATED` on this run's slots is
        cancelled by the season rollover with `cancel_fee_cents` of 0 and a
        full refund of its deposit; unlike an ordinary cancellation, no
        waitlist promotion fires at close."
        PRD §3.3: "Fourth, `COMMITTED` orders on the run persist untouched and
        may still report production completion afterwards — hull creation
        deliberately does not require the run to be `OPEN`."

        One batch close: an AT_PLANT hull (10 days -> 7500/9375 PEAK), an
        ALLOCATED order auto-cancelled with a waived fee, and the run CLOSED.

        Design: Corner/cross_cutting_layers/ops_run_checkpoint_close_recalculates_carrying_and_releases
        """
        world = setup_bookable_world(api, with_options=False, season="PEAK")
        dealer, model = world["dealer"], world["model"]
        s2 = create_slot(api, world["run"]["id"], slot_code="S2", capacity_hours=200)
        # An ALLOCATED order on S2 (auto-cancelled at close) ...
        o_al = book_order_no_options(api, dealer, model, slot_id=s2["id"])
        assert o_al["status"] == "ALLOCATED"
        # ... and a COMMITTED order on S1 whose hull stays AT_PLANT.
        o_cm = book_order_no_options(api, dealer, model, slot_id=world["slot"]["id"])
        o_cm = confirm_order(api, o_cm, dealer)
        # Hull completed at the startup clock 2026-08-01 and left AT_PLANT.
        create_hull(api, o_cm["id"])
        set_clock(api, "2026-08-11T00:00:00Z")
        run = validate_success(api.close_production_run(world["run"]["id"], PLANNER), 200)
        assert run["status"] == "CLOSED"
        assert run["total_carrying_actual_cents"] == 7500, "one AT_PLANT hull x 10d x 750"
        assert run["total_carrying_seasonal_cents"] == 9375, "PEAK factor 1.25"
        o_al_after = get_order(api, o_al["id"])
        assert o_al_after["status"] == "CANCELLED"
        assert o_al_after["cancel_fee_cents"] == 0
        assert o_al_after["refund_cents"] == 257500
        assert get_slot(api, world["slot"]["id"])["status"] == "RELEASED"
        assert get_slot(api, s2["id"])["status"] == "RELEASED"
