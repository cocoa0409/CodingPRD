"""Pricing and duration calculations: the forward-looking quote, the
chronological final price, their divergence on skipped add-ons, the multi-factor
duration estimate, and the nested rounding order with a plan discount.

Difficulty queue: dual_variant_calc, combinatorial_formula.
Corner queue: calculations (cap, no-skip parity).
"""
from test_helpers import validate_success
from test_helpers import fixtures as fx


class TestQuoteVsFinalDivergence:
    def test_quote_counts_all_addons_final_drops_skipped(self, api):
        """PRD §3.5: "Whenever a requested add-on is skipped, the final price is
        strictly less than the quote, so quoted_price_cents and final_price_cents
        legitimately differ."
        PRD §3.5: "adds the add-on total counting only the snapshotted prices of
        attached add-ons whose add_on_id is not in skipped_add_on_ids."

        Design: Difficulty/dual_variant_calc/quote_vs_final_price_diverge_on_skipped_addon
        """
        fx.set_clock("2026-06-10T08:00:00Z")
        deshed = fx.create_add_on(code="DESHED", price_cents=2000, duration_minutes=30)
        nail = fx.create_add_on(code="NAIL_TRIM", price_cents=1000, duration_minutes=10)
        world = fx.setup_world(zip_code="90001", tier_code="FULL_GROOM",
                               base_price_cents=6000, duration_multiplier=1.50,
                               base_service_minutes=60, weight_lbs=40,
                               coat_condition="NORMAL", behavioral_flag="CALM",
                               has_show_equipment=True)
        appt = fx.create_scheduled_appointment(
            world, "2026-06-10T09:30:00Z", add_on_ids=[deshed["id"], nail["id"]])
        assert appt["quoted_price_cents"] == 9000, appt

        resp = api.complete_appointment(
            appt["id"], {"skipped_add_on_ids": [nail["id"]]},
            fx.make_groomer_headers(world["groomer"]["id"]))
        data = validate_success(resp, 200)
        assert data["final_price_cents"] == 8000, data
        assert data["quoted_price_cents"] != data["final_price_cents"], data

    def test_final_equals_quote_when_nothing_skipped(self, api):
        """PRD §3.5: "adds the add-on total counting only the snapshotted prices of
        attached add-ons whose add_on_id is not in skipped_add_on_ids."

        Design: Corner/calculations/final_price_no_skip_equals_quote
        """
        fx.set_clock("2026-07-05T08:00:00Z")
        deshed = fx.create_add_on(code="DESHED", price_cents=2000, duration_minutes=30)
        nail = fx.create_add_on(code="NAIL_TRIM", price_cents=1000, duration_minutes=10)
        world = fx.setup_world(zip_code="10013", tier_code="FULL_GROOM",
                               base_price_cents=6000, duration_multiplier=1.00,
                               base_service_minutes=50, weight_lbs=30,
                               window_start="2026-07-05T09:00:00Z",
                               window_end="2026-07-05T17:00:00Z",
                               service_date="2026-07-05T00:00:00Z")
        appt = fx.create_scheduled_appointment(
            world, "2026-07-05T09:30:00Z", add_on_ids=[deshed["id"], nail["id"]])
        assert appt["quoted_price_cents"] == 9000, appt
        data = fx.complete(appt["id"], world["groomer"]["id"])
        assert data["final_price_cents"] == 9000, data
        assert data["quoted_price_cents"] == 9000, data


class TestNoShowFeeVariants:
    def _world_with_two_prior_strikes(self, zip_code, clock):
        """Build a world whose customer already carries 2 no_show_strikes."""
        fx.set_clock(clock)
        world = fx.setup_world(zip_code=zip_code, tier_code="FULL_GROOM",
                               base_price_cents=6000, duration_multiplier=1.00,
                               base_service_minutes=50, weight_lbs=20,
                               window_start=f"{clock[:11]}09:00:00Z",
                               window_end=f"{clock[:11]}17:00:00Z",
                               service_date=f"{clock[:11]}00:00:00Z")
        fx.accrue_no_show_strikes(world, 2, first_slot=f"{clock[:11]}09:00:00Z")
        return world

    def test_repeat_offender_fee_is_escalated(self, api):
        """PRD §3.5: "The customer's strike count is read immediately before this
        no-show is registered: if that prior count is at least 2, a flat repeat
        penalty of 1500 cents is added to the percent-of-quote base; otherwise no
        penalty is added."

        Design: Difficulty/dual_variant_calc/no_show_fee_standard_vs_repeat_escalated
        """
        clock = "2026-06-10T10:00:00Z"
        world = self._world_with_two_prior_strikes("90002", clock)
        third = fx.create_scheduled_appointment(world, "2026-06-10T13:00:00Z")
        fx.no_show(third["id"])
        fees = fx.fees_for_appointment(third["id"])
        assert len(fees) == 1, fees
        assert fees[0]["amount_cents"] == 4500, fees  # 3000 + 1500 repeat penalty

    def test_first_offender_fee_is_standard(self, api):
        """PRD §3.5: "The fee starts at 50 percent of the appointment's pinned
        quoted_price_cents, rounded half-up to a whole cent."

        Design: Difficulty/dual_variant_calc/no_show_fee_standard_vs_repeat_escalated
        """
        fx.set_clock("2026-06-10T10:00:00Z")
        world = fx.setup_world(zip_code="90002", tier_code="FULL_GROOM",
                               base_price_cents=6000, duration_multiplier=1.00,
                               base_service_minutes=50, weight_lbs=20)
        first = fx.create_scheduled_appointment(world, "2026-06-10T09:00:00Z")
        fx.no_show(first["id"])
        fees = fx.fees_for_appointment(first["id"])
        assert len(fees) == 1, fees
        assert fees[0]["amount_cents"] == 3000, fees  # 50% of 6000, no penalty

    def test_no_show_strikes_increment_to_three(self, api):
        """PRD §3.9: "The customer's no_show_strikes is the count of such non-waived
        strike events whose triggering appointment's reserved slot_start falls within
        the trailing 90 days of the current clock."

        Design: Difficulty/dual_variant_calc/no_show_fee_standard_vs_repeat_escalated
        """
        clock = "2026-06-10T10:00:00Z"
        world = self._world_with_two_prior_strikes("90002", clock)
        third = fx.create_scheduled_appointment(world, "2026-06-10T13:00:00Z")
        fx.no_show(third["id"])
        cust = fx.get_customer(world["customer"]["id"])
        assert cust["no_show_strikes"] == 3, cust

    def test_no_show_fee_capped_at_eight_thousand(self, api):
        """PRD §3.5: "The resulting amount is then capped at 8000 cents — the final
        fee is the smaller of the computed amount and 8000 cents."

        Design: Corner/calculations/no_show_fee_cap_applied
        """
        fx.set_clock("2026-07-04T10:00:00Z")
        # SHOW_CUT quoted at 18000 -> 50% = 9000, +1500 = 10500, capped to 8000.
        world = fx.setup_world(zip_code="10012", tier_code="SHOW_CUT",
                               base_price_cents=18000, duration_multiplier=2.00,
                               base_service_minutes=50, weight_lbs=40,
                               van_max_stops=6, has_show_equipment=True,
                               window_start="2026-07-04T08:00:00Z",
                               window_end="2026-07-04T18:00:00Z",
                               service_date="2026-07-04T00:00:00Z")
        # Accrue two prior strikes using a cheap FULL_GROOM tier on the same world.
        cheap = fx.create_service_tier(code="FULL_GROOM", base_price_cents=6000,
                                       duration_multiplier=1.00)
        for i, slot in enumerate(["2026-07-04T08:00:00Z", "2026-07-04T09:30:00Z"]):
            a = fx.create_appointment(world["pet"]["id"], cheap["id"], world["customer"]["id"])
            fx.quote(a["id"])
            fx.schedule(a["id"], world["route_day"]["id"], slot)
            fx.no_show(a["id"])
        third = fx.create_scheduled_appointment(world, "2026-07-04T11:00:00Z")
        assert third["quoted_price_cents"] == 18000, third
        fx.no_show(third["id"])
        fees = fx.fees_for_appointment(third["id"])
        assert len(fees) == 1, fees
        assert fees[0]["amount_cents"] == 8000, fees


class TestDurationEstimate:
    def test_multifactor_nonlinear_estimate(self, api):
        """PRD §3.3: "That baseline is multiplied by the tier's duration_multiplier,
        and the product is rounded up to the next whole minute; this ceiling is
        applied exactly once, here. To that tier-scaled figure the server adds a
        size surcharge of 20 minutes when the pet's weight_lbs is greater than 60
        pounds (and nothing otherwise), a de-matting allowance of 25 minutes when
        the pet's coat_condition is MATTED (and nothing otherwise), and the sum of
        the duration_minutes of every add-on currently attached to the appointment."

        Design: Difficulty/combinatorial_formula/duration_estimate_multifactor_nonlinear
        """
        fx.set_clock("2026-06-11T08:00:00Z")
        deshed = fx.create_add_on(code="DESHED", price_cents=2000, duration_minutes=30)
        world = fx.setup_world(zip_code="90003", tier_code="FULL_GROOM",
                               base_price_cents=6000, duration_multiplier=1.50,
                               base_service_minutes=60, weight_lbs=70,
                               coat_condition="MATTED", behavioral_flag="CALM",
                               with_groomer=False)
        appt = fx.create_appointment(world["pet"]["id"], world["tier"]["id"], world["customer"]["id"])
        fx.attach_add_on(appt["id"], deshed["id"], world["customer"]["id"])
        quoted = fx.quote(appt["id"])
        # ceil(60*1.50)=90 + 20 (heavy) + 25 (matted) + 30 (deshed) = 165
        assert quoted["estimated_minutes"] == 165, quoted

    def test_estimate_recomputed_on_requote(self, api):
        """PRD §3.3: "Each quote issuance — first quote or re-quote — recomputes
        both the duration estimate and the forward-looking price from the pet, tier,
        and currently attached add-ons, pins them onto the appointment, increments
        quote_round by one, and bumps the appointment's version."

        Design: Difficulty/combinatorial_formula/duration_estimate_multifactor_nonlinear
        """
        fx.set_clock("2026-06-11T08:00:00Z")
        world = fx.setup_world(zip_code="90003", tier_code="FULL_GROOM",
                               base_price_cents=6000, duration_multiplier=1.50,
                               base_service_minutes=60, weight_lbs=70,
                               coat_condition="MATTED", with_groomer=False)
        deshed = fx.create_add_on(code="DESHED", price_cents=2000, duration_minutes=30)
        appt = fx.create_appointment(world["pet"]["id"], world["tier"]["id"], world["customer"]["id"])
        first = fx.quote(appt["id"])
        assert first["estimated_minutes"] == 135, first  # 90 + 20 + 25, no add-on yet
        fx.attach_add_on(appt["id"], deshed["id"], world["customer"]["id"])
        second = fx.quote(appt["id"])
        assert second["estimated_minutes"] == 165, second  # add-on now counted


class TestQuotePriceRounding:
    def test_nested_rounding_order_with_plan_discount(self, api):
        """PRD §3.3: "A coat loading is added when the pet's coat_condition is
        MATTED: it equals 30 percent of the tier base price, rounded half-up to a
        whole cent at this per-component step (zero when the coat is not matted)."
        PRD §3.3: "If the appointment is plan-generated (its recurring_plan_id is
        set), a loyalty discount is computed as the plan's discount_pct of that
        gross, rounded half-up to a whole cent only after the gross has been summed,
        and subtracted; otherwise the discount is zero."

        Design: Difficulty/combinatorial_formula/quote_price_nested_rounding_order
        """
        fx.set_clock("2026-06-11T08:00:00Z")
        # BATH_ONLY base 3000, MATTED + heavy + DESHED 2000, plan discount 0.10.
        tier = fx.create_service_tier(code="BATH_ONLY", base_price_cents=3000,
                                      duration_multiplier=1.00)
        breed = fx.create_breed(base_service_minutes=40, coat_type="DOUBLE", size_class="LARGE")
        deshed = fx.create_add_on(code="DESHED", price_cents=2000, duration_minutes=30)
        customer = fx.create_customer(service_zip="90004")
        pet = fx.create_pet(customer["id"], breed["id"], weight_lbs=70,
                            coat_condition="MATTED", behavioral_flag="CALM")
        fx.upload_rabies(pet["id"], customer["id"])
        plan = fx.create_recurring_plan(pet["id"], tier["id"], customer["id"],
                                        cadence_days=28, discount_pct=0.10)
        appt = fx.generate_plan_appointment(plan["id"])
        fx.attach_add_on(appt["id"], deshed["id"], customer["id"])
        quoted = fx.quote(appt["id"])
        # coat round(900)=900, size round(450)=450, gross 3000+900+450+2000=6350
        # discount round(6350*0.10)=635 -> 5715
        assert quoted["quoted_price_cents"] == 5715, quoted

    def test_plan_generated_appointment_carries_plan_id(self, api):
        """PRD §3.8: "Generation creates a new REQUESTED appointment with its
        recurring_plan_id set to this plan and its service_tier_id copied from the
        plan, and bumps the plan's version."

        Design: Difficulty/combinatorial_formula/quote_price_nested_rounding_order
        """
        tier = fx.create_service_tier(code="BATH_ONLY", base_price_cents=3000,
                                      duration_multiplier=1.00)
        breed = fx.create_breed(base_service_minutes=40)
        customer = fx.create_customer(service_zip="90004")
        pet = fx.create_pet(customer["id"], breed["id"], weight_lbs=70)
        plan = fx.create_recurring_plan(pet["id"], tier["id"], customer["id"],
                                        cadence_days=28, discount_pct=0.10)
        appt = fx.generate_plan_appointment(plan["id"])
        assert appt["recurring_plan_id"] == plan["id"], appt
        assert appt["service_tier_id"] == tier["id"], appt
        assert appt["status"] == "REQUESTED", appt
