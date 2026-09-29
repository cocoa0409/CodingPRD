"""The 24-hour demand projection: variant choice, per-customer rounding, empty sets."""

from test_helpers import (
    active_agreement,
    assert_energy,
    assert_forecast_projection,
    assert_loop_state,
    assert_money,
    commercial_rate_schedule,
    create_forecast,
    create_loop,
    empty_customer_stack,
    hospital_rate_schedule,
    publish_forecast,
    read_agreement,
    read_forecast,
    read_loop,
    riverside_residential_stack,
    set_clock,
)


def _downtown_two_customer_loop():
    """LOOP-A carrying a 4000 kW hospital and a 2500 kW commercial office."""
    set_clock()
    loop = create_loop(
        code="LOOP-A",
        name="Downtown Loop A",
        service_mode="DUAL",
        design_supply_temp_c=95.0,
        max_pressure_kpa=1600.0,
        rated_capacity_kw=9000.0,
    )
    hospital_tariff = hospital_rate_schedule()
    commercial_tariff = commercial_rate_schedule()
    hospital = active_agreement(
        loop["id"],
        hospital_tariff["id"],
        customer_name="City Hospital",
        customer_class="HOSPITAL",
        reserved_capacity_kw=4000.0,
        service_mode="DUAL",
    )
    office = active_agreement(
        loop["id"],
        commercial_tariff["id"],
        customer_name="Downtown Offices",
        customer_class="COMMERCIAL_OFFICE",
        reserved_capacity_kw=2500.0,
        service_mode="DUAL",
    )
    return {"loop": loop, "hospital": hospital, "office": office}


class TestVariantDivergence:
    """Two publications of the same weather picture under the two variants."""

    def test_weather_normal_variant_uses_the_stored_degree_hours_unchanged(self):
        """Publishing under WEATHER_NORMAL_PROVISIONAL applies the stored degree hours.

        PRD: "Under `WEATHER_NORMAL_PROVISIONAL` the heating degree hours are the
        stored `heating_degree_hours` and the cooling degree hours are the stored
        `cooling_degree_hours`, both used unchanged; the two actual fields are
        ignored entirely."

        Design: Difficulty/dual_variant_calc/forecast_weather_normal_vs_actual_weighted_variant_divergence
        """
        stack = _downtown_two_customer_loop()
        draft = create_forecast(
            stack["loop"]["id"],
            "2026-08-05T00:00:00Z",
            occupancy_profile="WEEKDAY_FULL",
            heating_degree_hours=120.0,
            cooling_degree_hours=340.0,
            actual_heating_degree_hours=150.0,
            actual_cooling_degree_hours=300.0,
        )

        published = publish_forecast(draft["id"], "WEATHER_NORMAL_PROVISIONAL")

        assert_forecast_projection(
            published,
            coincident_demand_kw=7475.76,
            projected_energy_mwh=111.239,
            contributing_agreement_count=2,
            forecast_state="PUBLISHED",
            variant_applied="WEATHER_NORMAL_PROVISIONAL",
        )

    def test_actual_weighted_variant_blends_the_degree_hours_before_the_adder(self):
        """ACTUAL_WEIGHTED_FINAL blends seven tenths actual with three tenths normal.

        PRD: "Under `ACTUAL_WEIGHTED_FINAL` the heating degree hours are seven
        tenths of `actual_heating_degree_hours` plus three tenths of
        `heating_degree_hours`, and that blended figure is itself rounded half-up
        to two decimal places before anything else uses it".

        Design: Difficulty/dual_variant_calc/forecast_weather_normal_vs_actual_weighted_variant_divergence
        """
        stack = _downtown_two_customer_loop()
        draft = create_forecast(
            stack["loop"]["id"],
            "2026-08-05T00:00:00Z",
            occupancy_profile="WEEKDAY_FULL",
            heating_degree_hours=120.0,
            cooling_degree_hours=340.0,
            actual_heating_degree_hours=150.0,
            actual_cooling_degree_hours=300.0,
        )

        published = publish_forecast(draft["id"], "ACTUAL_WEIGHTED_FINAL")

        assert_forecast_projection(
            published,
            coincident_demand_kw=7470.47,
            projected_energy_mwh=111.161,
            contributing_agreement_count=2,
            forecast_state="PUBLISHED",
            variant_applied="ACTUAL_WEIGHTED_FINAL",
        )

    def test_the_two_variants_diverge_by_five_kilowatts_and_twenty_nine_cents(self):
        """Both projections stand side by side and differ only through the variant.

        PRD: "Second, the degree hours to use are chosen by variant, and the two
        variants differ in exactly one place."

        Design: Difficulty/dual_variant_calc/forecast_weather_normal_vs_actual_weighted_variant_divergence
        """
        stack = _downtown_two_customer_loop()
        weather_inputs = {
            "occupancy_profile": "WEEKDAY_FULL",
            "heating_degree_hours": 120.0,
            "cooling_degree_hours": 340.0,
            "actual_heating_degree_hours": 150.0,
            "actual_cooling_degree_hours": 300.0,
        }
        provisional_draft = create_forecast(
            stack["loop"]["id"], "2026-08-05T00:00:00Z", **weather_inputs
        )
        final_draft = create_forecast(
            stack["loop"]["id"], "2026-08-05T00:00:00Z", **weather_inputs
        )

        provisional = publish_forecast(provisional_draft["id"], "WEATHER_NORMAL_PROVISIONAL")
        final = publish_forecast(final_draft["id"], "ACTUAL_WEIGHTED_FINAL")

        assert_money(
            provisional["coincident_demand_kw"] - final["coincident_demand_kw"],
            5.29,
            "variant divergence",
        )
        assert_energy(
            provisional["projected_energy_mwh"] - final["projected_energy_mwh"],
            0.078,
            "energy divergence",
        )

    def test_the_later_publication_supersedes_the_earlier_one_on_the_same_day(self):
        """A second publication for the same loop and day retires the first.

        PRD: "Publication supersedes competition: any **other** forecast on the
        same `loop_id` with the same `service_date` that is currently `PUBLISHED`
        is cascaded from `PUBLISHED` to `SUPERSEDED` and has its `version`
        incremented by 1."

        Design: Difficulty/dual_variant_calc/forecast_weather_normal_vs_actual_weighted_variant_divergence
        """
        stack = _downtown_two_customer_loop()
        weather_inputs = {
            "occupancy_profile": "WEEKDAY_FULL",
            "heating_degree_hours": 120.0,
            "cooling_degree_hours": 340.0,
            "actual_heating_degree_hours": 150.0,
            "actual_cooling_degree_hours": 300.0,
        }
        first = publish_forecast(
            create_forecast(stack["loop"]["id"], "2026-08-05T00:00:00Z", **weather_inputs)["id"],
            "WEATHER_NORMAL_PROVISIONAL",
        )
        second = publish_forecast(
            create_forecast(stack["loop"]["id"], "2026-08-05T00:00:00Z", **weather_inputs)["id"],
            "ACTUAL_WEIGHTED_FINAL",
        )

        assert read_forecast(first["id"])["forecast_state"] == "SUPERSEDED"
        assert read_forecast(second["id"])["forecast_state"] == "PUBLISHED"


class TestPerCustomerRounding:
    """Each customer's diversified contribution is rounded on its own."""

    def test_three_awkward_reservations_are_rounded_before_they_are_summed(self):
        """A weekend projection over 1010, 2035 and 3060 kW lands on 2943.28.

        PRD: "Each agreement contributes its `reserved_capacity_kw` multiplied by
        a class diversity factor for its `customer_class` and multiplied by the
        occupancy factor, and **that per-agreement product is rounded half-up to
        two decimal places before it joins the running sum**."

        Design: Difficulty/combinatorial_formula/per_agreement_contribution_rounded_before_summation_in_forecast
        """
        stack = riverside_residential_stack()

        published = publish_forecast(
            create_forecast(
                stack["loop"]["id"],
                "2026-08-08T00:00:00Z",
                occupancy_profile="WEEKEND_REDUCED",
            )["id"],
            "WEATHER_NORMAL_PROVISIONAL",
        )

        assert_forecast_projection(
            published,
            coincident_demand_kw=2943.28,
            projected_energy_mwh=43.796,
            contributing_agreement_count=3,
        )

    def test_summing_the_unrounded_products_would_have_given_a_higher_peak(self):
        """The stated ordering costs exactly one hundredth of a kilowatt.

        PRD: "rounding a sum of unrounded terms and summing a list of rounded
        terms give different answers, and the tests assert the stated one."

        Design: Difficulty/combinatorial_formula/per_agreement_contribution_rounded_before_summation_in_forecast
        """
        stack = riverside_residential_stack()

        published = publish_forecast(
            create_forecast(
                stack["loop"]["id"],
                "2026-08-08T00:00:00Z",
                occupancy_profile="WEEKEND_REDUCED",
            )["id"],
            "WEATHER_NORMAL_PROVISIONAL",
        )

        assert published["coincident_demand_kw"] != 2943.29
        assert_money(published["coincident_demand_kw"], 2943.28, "coincident_demand_kw")

    def test_the_reduced_weekend_occupancy_factor_scales_every_contribution(self):
        """The same three customers on a full weekday scale up by the occupancy factor.

        PRD: "First, an occupancy factor is read from the `occupancy_profile`: a
        full weekday counts for the whole of the diversified load, a reduced
        weekend counts for 0.72 of it, and a minimal holiday counts for 0.45 of it."

        Design: Difficulty/combinatorial_formula/per_agreement_contribution_rounded_before_summation_in_forecast
        """
        stack = riverside_residential_stack()

        weekday = publish_forecast(
            create_forecast(
                stack["loop"]["id"],
                "2026-08-10T00:00:00Z",
                occupancy_profile="WEEKDAY_FULL",
            )["id"],
            "WEATHER_NORMAL_PROVISIONAL",
        )

        assert_forecast_projection(
            weekday,
            coincident_demand_kw=4087.91,
            contributing_agreement_count=3,
        )


class TestEmptyContributorSet:
    """A day on which no agreement is in service still publishes cleanly."""

    def test_a_service_window_closing_on_the_service_date_contributes_nothing(self):
        """The only live customer ends exactly on the forecast day, so the set is empty.

        PRD: "The input set is every connection agreement on the forecast's loop
        whose `contract_state` is `ACTIVE`, whose `service_start_date` is at or
        before the forecast's `service_date`, and whose `service_end_date` is
        strictly after the forecast's `service_date`."

        Design: Difficulty/boundary_precision_check/empty_active_agreement_set_yields_zero_coincident_demand_on_publish
        """
        stack = empty_customer_stack()

        published = publish_forecast(
            create_forecast(
                stack["loop"]["id"],
                "2026-08-01T00:00:00Z",
                occupancy_profile="WEEKDAY_FULL",
            )["id"],
            "WEATHER_NORMAL_PROVISIONAL",
        )

        assert_forecast_projection(
            published,
            coincident_demand_kw=0.00,
            projected_energy_mwh=0.000,
            contributing_agreement_count=0,
            forecast_state="PUBLISHED",
            variant_applied="WEATHER_NORMAL_PROVISIONAL",
        )

    def test_a_pending_customer_is_not_a_contributor_but_the_expired_one_still_reserves(self):
        """Only ACTIVE agreements project load; reservation accounting is separate.

        PRD: "`committed_reserved_kw`, the sum of `reserved_capacity_kw` across
        the agreements on this loop whose `contract_state` is `ACTIVE` or
        `SUSPENDED`".

        Design: Difficulty/boundary_precision_check/empty_active_agreement_set_yields_zero_coincident_demand_on_publish
        """
        stack = empty_customer_stack()

        publish_forecast(
            create_forecast(
                stack["loop"]["id"],
                "2026-08-01T00:00:00Z",
                occupancy_profile="WEEKDAY_FULL",
            )["id"],
            "WEATHER_NORMAL_PROVISIONAL",
        )

        assert read_agreement(stack["expiring"]["id"])["contract_state"] == "ACTIVE"
        assert read_agreement(stack["pending"]["id"])["contract_state"] == "PENDING_CAPACITY"
        assert_loop_state(read_loop(stack["loop"]["id"]), committed_reserved_kw=1000.0)

    def test_a_day_inside_the_service_window_does_pick_the_customer_up(self):
        """Moving the service date one day earlier brings the customer back in.

        PRD: "a `service_start_date` at which service begins inclusively together
        with a `service_end_date` at which it ends exclusively."

        Design: Difficulty/boundary_precision_check/empty_active_agreement_set_yields_zero_coincident_demand_on_publish
        """
        stack = empty_customer_stack()

        published = publish_forecast(
            create_forecast(
                stack["loop"]["id"],
                "2026-07-31T00:00:00Z",
                occupancy_profile="WEEKDAY_FULL",
            )["id"],
            "WEATHER_NORMAL_PROVISIONAL",
        )

        assert_forecast_projection(
            published,
            coincident_demand_kw=756.00,
            contributing_agreement_count=1,
        )
