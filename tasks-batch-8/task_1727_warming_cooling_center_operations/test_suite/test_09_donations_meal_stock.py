"""Donation stock dual variants, meal-plan rounding order, meal-stock
conservation, and terminal donation/meal-service states (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_meal_service,
    get_site_activation,
    plan_meal_service,
    pledge_donation,
    receive_donation,
    serve_meal,
    setup_meal_conservation_scene,
    setup_rounding_scene,
    setup_standby_episode_with_opening_site,
    setup_stock_scene,
    validate_error,
)


class TestSupplyStockDualVariants:
    def test_meal_stock_on_hand_counts_received_only(self, api):
        """PRD §3.6: "`meal_stock_on_hand` is the sum of `quantity` over the
        activation's `RECEIVED` meal donations minus the `served_count` totals
        of its `SERVED` meal services — the physical stock that serving is
        gated against."

        Design: Difficulty/dual_variant_calc/supply_stock_projected_includes_pledged_on_hand_does_not
        """
        ws = setup_stock_scene()  # 50 MEAL pledged + 100 MEAL received
        sa = get_site_activation(ws["site_activation"]["id"])
        assert sa["meal_stock_on_hand"] == 100

    def test_meal_stock_projected_adds_pledged(self, api):
        """PRD §3.6: "`meal_stock_projected` adds the `quantity` of meal
        donations still in `PLEDGED` to the on-hand figure, giving planners a
        forward view that is never below the on-hand value for the same
        data."

        Design: Difficulty/dual_variant_calc/supply_stock_projected_includes_pledged_on_hand_does_not
        """
        ws = setup_stock_scene()  # 50 MEAL pledged + 100 MEAL received
        sa = get_site_activation(ws["site_activation"]["id"])
        assert sa["meal_stock_projected"] == 150
        assert sa["meal_stock_projected"] >= sa["meal_stock_on_hand"]


class TestMealPlanRounding:
    def test_planned_meals_rounds_up_per_service(self, api):
        """PRD §3.6: "Creating one names a `service_date` — its time component
        is ignored — and a `meal_period` of `BREAKFAST`, `LUNCH` or `DINNER`,
        and pins `planned_meals` at the creation moment: the attendance
        snapshot is `occupied_beds` plus `reserved_beds` at that instant,
        multiplied by the period buffer — 1.10 for breakfast, 1.15 for lunch,
        1.25 for dinner — and rounded up to a whole meal."

        Design: Difficulty/combinatorial_formula/meal_planned_round_per_service_then_sum
        """
        ws = setup_rounding_scene()  # attendance snapshot: 3 checked-in
        sa_id = ws["site_activation"]["id"]
        breakfast = plan_meal_service(sa_id, "2026-08-10T00:00:00Z",
                                      "BREAKFAST", ws["lead1_headers"])
        lunch = plan_meal_service(sa_id, "2026-08-10T00:00:00Z", "LUNCH",
                                  ws["lead1_headers"])
        dinner = plan_meal_service(sa_id, "2026-08-10T00:00:00Z", "DINNER",
                                   ws["lead1_headers"])
        assert_meal_service(breakfast)
        assert breakfast["planned_meals"] == 4   # ceil(3 * 1.10)
        assert lunch["planned_meals"] == 4       # ceil(3 * 1.15)
        assert dinner["planned_meals"] == 4      # ceil(3 * 1.25)

    def test_planned_meals_total_is_sum_of_rounded_services(self, api):
        """PRD §3.6: "Each service rounds its own plan individually; any daily
        or site total is the sum of those per-service rounded values, and
        rounding the sum of unrounded values instead is not permitted, because
        it yields a different number." — with attendance 3 the per-service
        rounding yields 4 + 4 + 4 = 12 where sum-then-round would yield 11.

        Design: Difficulty/combinatorial_formula/meal_planned_round_per_service_then_sum
        """
        ws = setup_rounding_scene()
        sa_id = ws["site_activation"]["id"]
        total = 0
        for period in ("BREAKFAST", "LUNCH", "DINNER"):
            service = plan_meal_service(sa_id, "2026-08-10T00:00:00Z", period,
                                        ws["lead1_headers"])
            total += service["planned_meals"]
        assert total == 12


class TestMealStockConservation:
    def test_meal_stock_conserved_through_receive_and_serve(self, api):
        """PRD §3.6: "`meal_stock_on_hand` is the sum of `quantity` over the
        activation's `RECEIVED` meal donations minus the `served_count` totals
        of its `SERVED` meal services" and "a successful serve reduces
        `meal_stock_on_hand` by exactly `served_count`." — 100 received, 40
        then 60 served, leaves exactly 0.

        Design: Difficulty/compensating_invariant/meal_stock_conserved_through_receive_and_serve
        """
        ws = setup_meal_conservation_scene()
        serve_meal(ws["ms1"]["id"], 40, lead_headers=ws["lead1_headers"])
        sa_mid = get_site_activation(ws["site_activation"]["id"])
        assert sa_mid["meal_stock_on_hand"] == 60   # 100 == 40 + 60

        serve_meal(ws["ms2"]["id"], 60, lead_headers=ws["lead1_headers"])
        sa_end = get_site_activation(ws["site_activation"]["id"])
        assert sa_end["meal_stock_on_hand"] == 0    # 100 == 100 + 0

    def test_serve_beyond_stock_rejected(self, api):
        """PRD §3.6: "The `SiteLead` reports the non-negative `served_count`,
        which may not exceed the activation's `meal_stock_on_hand` — otherwise
        the serve is rejected with `ERR_INSUFFICIENT_MEAL_STOCK` — and a
        successful serve reduces `meal_stock_on_hand` by exactly
        `served_count`."

        Design: Difficulty/compensating_invariant/meal_stock_conserved_through_receive_and_serve
        """
        ws = setup_meal_conservation_scene()
        serve_meal(ws["ms1"]["id"], 40, lead_headers=ws["lead1_headers"])
        serve_meal(ws["ms2"]["id"], 60, lead_headers=ws["lead1_headers"])

        # Stock is exactly 0; even one more meal breaks conservation.
        resp = api.serve_meal_service(ws["ms3"]["id"], {"served_count": 1},
                                      ws["lead1_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_MEAL_STOCK,
                       expected_status=409)
        assert (get_site_activation(ws["site_activation"]["id"])
                ["meal_stock_on_hand"] == 0)


class TestTerminalSupplyStates:
    def test_donation_receive_twice_rejected(self, api):
        """PRD §3.6: "A pledge stands in `PLEDGED` until the same role
        confirms receipt, moving it to `RECEIVED`." — a second receipt has no
        source state.
        PRD §2.9: "Fifth are state guards, evaluated parents-first — episode
        before site activation before stay or dispatch — yielding the
        transition-specific codes (`ERR_INVALID_STATE`, ...)".

        Design: Corner/state_machines/donation_receive_twice_rejected
        """
        ws = setup_standby_episode_with_opening_site()
        donation = pledge_donation(ws["site_activation"]["id"], "FoodBank",
                                   "MEAL", 10, lead_headers=ws["lead1_headers"])
        receive_donation(donation["id"], lead_headers=ws["lead1_headers"])

        resp = api.receive_donation(donation["id"], ws["lead1_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert (get_site_activation(ws["site_activation"]["id"])
                ["meal_stock_on_hand"] == 10)

    def test_meal_service_serve_twice_rejected(self, api):
        """PRD §3.6: "Serving moves a service from `PLANNED` to `SERVED`." — a
        second serve has no source state.
        PRD §2.9: "Fifth are state guards, evaluated parents-first — episode
        before site activation before stay or dispatch — yielding the
        transition-specific codes (`ERR_INVALID_STATE`, ...)".

        Design: Corner/state_machines/meal_service_serve_twice_rejected
        """
        ws = setup_standby_episode_with_opening_site()
        donation = pledge_donation(ws["site_activation"]["id"], "FoodBank",
                                   "MEAL", 10, lead_headers=ws["lead1_headers"])
        receive_donation(donation["id"], lead_headers=ws["lead1_headers"])
        service = plan_meal_service(ws["site_activation"]["id"],
                                    "2026-08-10T00:00:00Z", "LUNCH",
                                    lead_headers=ws["lead1_headers"])
        serve_meal(service["id"], 4, lead_headers=ws["lead1_headers"])

        resp = api.serve_meal_service(service["id"], {"served_count": 2},
                                      ws["lead1_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert (get_site_activation(ws["site_activation"]["id"])
                ["meal_stock_on_hand"] == 6)
