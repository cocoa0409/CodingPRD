"""Second-angle tests for the depth (difficulty) instances — each asserts a
distinct, PRD-derivable facet of the same rule (boundary X+1/X-1, the pinned
intermediate value, the non-overlap control, the alternate blocked pathway).

Difficulty queue: complements test_01 and test_04.
"""
from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.constants import NONEXISTENT_UUID


class TestQuotePinnedThenFinalDiverges:
    def test_quote_pins_full_basket_at_quoted_state(self, api):
        """PRD §3.3: "The add-on total is the sum of the snapshotted
        price_cents_snapshot of every add-on attached at quote time — at quote, this
        projects the full requested basket."

        Design: Difficulty/dual_variant_calc/quote_vs_final_price_diverge_on_skipped_addon
        """
        fx.set_clock("2026-06-10T08:00:00Z")
        deshed = fx.create_add_on(code="DESHED", price_cents=2000, duration_minutes=30)
        nail = fx.create_add_on(code="NAIL_TRIM", price_cents=1000, duration_minutes=10)
        world = fx.setup_world(zip_code="90001", tier_code="FULL_GROOM",
                               base_price_cents=6000, duration_multiplier=1.50,
                               base_service_minutes=60, weight_lbs=40,
                               coat_condition="NORMAL", has_show_equipment=True)
        appt = fx.create_appointment(world["pet"]["id"], world["tier"]["id"], world["customer"]["id"])
        fx.attach_add_on(appt["id"], deshed["id"], world["customer"]["id"])
        fx.attach_add_on(appt["id"], nail["id"], world["customer"]["id"])
        quoted = fx.quote(appt["id"])
        # 6000 tier + 2000 + 1000 add-ons; no loadings (NORMAL, 40lbs) = 9000
        assert quoted["status"] == "QUOTED", quoted
        assert quoted["quoted_price_cents"] == 9000, quoted


class TestValidationPrecedenceSecondAngle:
    def test_existence_beats_state_when_appointment_quoted(self, api):
        """PRD §2.9: "The first identifier that does not resolve causes the request
        to be rejected with ERR_NOT_FOUND (HTTP 404)."

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_schedule
        """
        fx.set_clock("2026-06-15T08:00:00Z")
        # Appointment is QUOTED (valid state) but the route_day_id does not exist;
        # existence (404) is still the governing failure for the body FK.
        tier = fx.create_service_tier(code="FULL_GROOM", base_price_cents=6000,
                                      duration_multiplier=1.00)
        breed = fx.create_breed(base_service_minutes=45, coat_type="CURLY", size_class="SMALL")
        customer = fx.create_customer(service_zip="90009")
        pet = fx.create_pet(customer["id"], breed["id"], weight_lbs=20)
        fx.upload_rabies(pet["id"], customer["id"])
        appt = fx.create_appointment(pet["id"], tier["id"], customer["id"])
        fx.quote(appt["id"])
        resp = api.schedule_appointment(appt["id"], {
            "route_day_id": NONEXISTENT_UUID,
            "slot_start": "2026-06-15T09:30:00Z",
            "expected_route_day_version": 0,
        }, fx.DISPATCH)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_vaccination_rejection_leaves_appointment_quoted(self, api):
        """PRD §3.4: "Then the pet's vaccination_status must again be VALID at the
        current clock, or the request is rejected with ERR_VACCINATION_REQUIRED
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/vaccination_safety_beats_zip_referential_on_schedule
        """
        fx.set_clock("2026-06-15T08:00:00Z")
        tier = fx.create_service_tier(code="FULL_GROOM", base_price_cents=6000,
                                      duration_multiplier=1.00)
        breed = fx.create_breed(base_service_minutes=40, coat_type="WIRE", size_class="SMALL")
        fx.create_groomer(handles_aggressive=True, skill_level="SENIOR")
        van = fx.create_van(max_stops=5)
        customer = fx.create_customer(service_zip="90010")
        pet = fx.create_pet(customer["id"], breed["id"], weight_lbs=18)
        fx.upload_rabies(pet["id"], customer["id"],
                         issued_on="2025-01-01T00:00:00Z", expires_on="2026-06-20T00:00:00Z")
        appt = fx.create_appointment(pet["id"], tier["id"], customer["id"])
        fx.quote(appt["id"])
        rd = fx.create_route_day(van["id"], coverage_zip="99999",
                                 service_date="2026-06-25T00:00:00Z",
                                 window_start="2026-06-25T09:00:00Z",
                                 window_end="2026-06-25T17:00:00Z")
        fx.set_clock("2026-06-25T08:00:00Z")
        resp = api.schedule_appointment(appt["id"], {
            "route_day_id": rd["id"], "slot_start": "2026-06-25T09:30:00Z",
            "expected_route_day_version": rd["version"],
        }, fx.DISPATCH)
        validate_error(resp, ApiErrorId.ERR_VACCINATION_REQUIRED.value)
        after = fx.get_success_data(api.get_appointment(appt["id"], fx.DISPATCH))
        assert after["status"] == "QUOTED", after  # no transition occurred


class TestBoundaryPrecisionSecondAngle:
    def test_route_capacity_one_minute_over_rejected(self, api):
        """PRD §3.4: "the boundary is inclusive, so exactly filling the window is
        allowed and one minute beyond is rejected with ERR_ROUTE_CAPACITY_EXCEEDED."

        Design: Difficulty/boundary_precision_check/route_capacity_exact_minute_boundary
        """
        fx.set_clock("2026-06-16T08:00:00Z")
        # Window 179 min. First stop 100 (load 115), second 50 (load 65) -> 180 > 179.
        tier130 = fx.create_service_tier(code="FULL_GROOM", base_price_cents=6000,
                                         duration_multiplier=1.00)
        tier50 = fx.create_service_tier(code="BATH_ONLY", base_price_cents=3000,
                                        duration_multiplier=1.00)
        breed130 = fx.create_breed(base_service_minutes=100, coat_type="DOUBLE", size_class="LARGE")
        breed50 = fx.create_breed(base_service_minutes=50, coat_type="SMOOTH", size_class="SMALL")
        fx.create_groomer(handles_aggressive=True, skill_level="SENIOR")
        fx.create_groomer(handles_aggressive=True, skill_level="SENIOR")
        van = fx.create_van(max_stops=5)
        customer = fx.create_customer(service_zip="90011")
        rd = fx.create_route_day(van["id"], coverage_zip="90011",
                                 service_date="2026-06-16T00:00:00Z",
                                 window_start="2026-06-16T09:00:00Z",
                                 window_end="2026-06-16T11:59:00Z")  # 179 min window
        pet_big = fx.create_pet(customer["id"], breed130["id"], name="Big", weight_lbs=50)
        fx.upload_rabies(pet_big["id"], customer["id"])
        pet_small = fx.create_pet(customer["id"], breed50["id"], name="Small", weight_lbs=20)
        fx.upload_rabies(pet_small["id"], customer["id"])
        a_big = fx.create_appointment(pet_big["id"], tier130["id"], customer["id"])
        fx.quote(a_big["id"])
        fx.schedule(a_big["id"], rd["id"], "2026-06-16T09:00:00Z")  # [09:00,10:40)
        a_small = fx.create_appointment(pet_small["id"], tier50["id"], customer["id"])
        fx.quote(a_small["id"])
        resp = api.schedule_appointment(a_small["id"], {
            "route_day_id": rd["id"], "slot_start": "2026-06-16T10:55:00Z",
            "expected_route_day_version": fx.current_route_version(rd["id"]),
        }, fx.DISPATCH)
        validate_error(resp, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED.value)

    def test_late_cancel_fee_charged_at_23h(self, api):
        """PRD §3.5: "if it is fewer than 24 hours the customer is charged a flat
        2500-cent late-cancel fee, the same depth-three cascade debits
        outstanding_fee_cents, and a strike is registered."

        Design: Difficulty/boundary_precision_check/late_cancel_hour_boundary_no_fee_at_exactly_24h
        """
        fx.set_clock("2026-06-17T10:00:00Z")
        world = fx.setup_world(zip_code="90012", tier_code="FULL_GROOM",
                               base_price_cents=6000, duration_multiplier=1.00,
                               base_service_minutes=50, weight_lbs=40,
                               window_start="2026-06-18T08:00:00Z",
                               window_end="2026-06-18T17:00:00Z",
                               service_date="2026-06-18T00:00:00Z")
        # slot_start 23h after clock (10:00 on 17th -> 09:00 on 18th).
        appt = fx.create_scheduled_appointment(world, "2026-06-18T09:00:00Z")
        cancelled = fx.cancel(appt["id"], world["customer"]["id"])
        assert cancelled["status"] == "CANCELLED", cancelled
        fees = fx.list_customer_fee_charges(world["customer"]["id"])
        assert len(fees) == 1, fees
        assert fees[0]["fee_type"] == "LATE_CANCEL", fees
        assert fees[0]["amount_cents"] == 2500, fees
        cust = fx.get_customer(world["customer"]["id"])
        assert cust["no_show_strikes"] == 1, cust


class TestCrossEntityStateBlocksSecondAngle:
    def test_suspended_customer_blocks_plan_generation(self, api):
        """PRD §3.8: "Generation requires that the plan is ACTIVE and that the owning
        customer's account_status is ACTIVE (a SUSPENDED customer cannot have new
        appointments generated, rejected with ERR_ACCOUNT_SUSPENDED)."

        Design: Difficulty/cross_entity_state_dependency/schedule_blocked_by_suspended_customer
        """
        fx.set_clock("2026-06-19T10:00:00Z")
        world = fx.setup_world(zip_code="90013", tier_code="FULL_GROOM",
                               base_price_cents=6000, duration_multiplier=1.00,
                               base_service_minutes=50, weight_lbs=40,
                               window_start="2026-06-19T09:00:00Z",
                               window_end="2026-06-19T17:00:00Z",
                               service_date="2026-06-19T00:00:00Z")
        fx.accrue_no_show_strikes(world, 3, first_slot="2026-06-19T09:00:00Z")
        cust = fx.get_customer(world["customer"]["id"])
        assert cust["account_status"] == "SUSPENDED", cust
        plan = fx.create_recurring_plan(world["pet"]["id"], world["tier"]["id"],
                                        world["customer"]["id"], cadence_days=28, discount_pct=0.05)
        resp = api.generate_appointment(plan["id"], fx.DISPATCH)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED.value)

    def test_dispatch_locks_routeday_status(self, api):
        """PRD §3.7: "A dispatcher dispatches a route day to lock it, advancing it
        from OPEN to LOCKED; this requires that at least one stop on the day is in
        RESERVED status. Once LOCKED, no new stops may be added."

        Design: Difficulty/cross_entity_state_dependency/schedule_blocked_by_locked_routeday
        """
        fx.set_clock("2026-06-20T08:00:00Z")
        world = fx.setup_world(zip_code="90014", tier_code="FULL_GROOM",
                               base_price_cents=6000, duration_multiplier=1.00,
                               base_service_minutes=50, weight_lbs=40,
                               window_start="2026-06-20T09:00:00Z",
                               window_end="2026-06-20T17:00:00Z",
                               service_date="2026-06-20T00:00:00Z")
        fx.create_scheduled_appointment(world, "2026-06-20T09:30:00Z")
        rd_before = fx.get_success_data(api.get_route_day(world["route_day"]["id"], fx.DISPATCH))
        assert rd_before["status"] == "OPEN", rd_before
        locked = fx.get_success_data(api.dispatch_route_day(world["route_day"]["id"], fx.DISPATCH))
        assert locked["status"] == "LOCKED", locked


class TestResourceOverlapSecondAngle:
    def test_stop_just_past_buffer_is_accepted(self, api):
        """PRD §3.4: "every other stop on the same route day ... is expanded by a
        15-minute travel buffer on both ends — from 15 minutes before its slot_start
        to 15 minutes after its slot_end — and if the requested interval overlaps any
        such buffered interval, the request is rejected with ERR_SLOT_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/route_stop_buffered_overlap_rejected
        """
        fx.set_clock("2026-06-21T08:00:00Z")
        tier70 = fx.create_service_tier(code="FULL_GROOM", base_price_cents=6000,
                                        duration_multiplier=1.00)
        tier50 = fx.create_service_tier(code="BATH_ONLY", base_price_cents=3000,
                                        duration_multiplier=1.00)
        breed70 = fx.create_breed(base_service_minutes=70, coat_type="DOUBLE", size_class="LARGE")
        breed50 = fx.create_breed(base_service_minutes=50, coat_type="SMOOTH", size_class="SMALL")
        fx.create_groomer(handles_aggressive=True, skill_level="SENIOR")
        fx.create_groomer(handles_aggressive=True, skill_level="SENIOR")
        van = fx.create_van(max_stops=5)
        customer = fx.create_customer(service_zip="90015")
        rd = fx.create_route_day(van["id"], coverage_zip="90015",
                                 service_date="2026-06-21T00:00:00Z",
                                 window_start="2026-06-21T09:00:00Z",
                                 window_end="2026-06-21T17:00:00Z")
        pet70 = fx.create_pet(customer["id"], breed70["id"], name="P70", weight_lbs=40)
        fx.upload_rabies(pet70["id"], customer["id"])
        pet50 = fx.create_pet(customer["id"], breed50["id"], name="P50", weight_lbs=20)
        fx.upload_rabies(pet50["id"], customer["id"])
        a70 = fx.create_appointment(pet70["id"], tier70["id"], customer["id"])
        fx.quote(a70["id"])
        fx.schedule(a70["id"], rd["id"], "2026-06-21T09:00:00Z")  # [09:00,10:10), buffered to 10:25
        a50 = fx.create_appointment(pet50["id"], tier50["id"], customer["id"])
        fx.quote(a50["id"])
        # request [10:25,11:15): starts exactly at the buffered end (half-open) -> no overlap.
        scheduled = fx.schedule(a50["id"], rd["id"], "2026-06-21T10:25:00Z")
        assert scheduled["status"] == "SCHEDULED", scheduled

    def test_groomer_back_to_back_is_allowed(self, api):
        """PRD §3.4: "two appointments that are exactly back-to-back (one stop's
        slot_end equal to the next stop's slot_start) are allowed and only a true
        overlap excludes the groomer."

        Design: Difficulty/resource_temporal_overlap/groomer_double_booking_excludes_only_qualified_groomer
        """
        fx.set_clock("2026-06-22T08:00:00Z")
        tier = fx.create_service_tier(code="FULL_GROOM", base_price_cents=6000,
                                      duration_multiplier=1.20)
        breed = fx.create_breed(base_service_minutes=50, coat_type="WIRE", size_class="LARGE")
        spec = fx.create_groomer(skill_level="SENIOR", handles_aggressive=True)
        fx.create_groomer(skill_level="JUNIOR", handles_aggressive=False)
        van1 = fx.create_van(max_stops=5)
        van2 = fx.create_van(max_stops=5)
        customer = fx.create_customer(service_zip="90016")
        rd1 = fx.create_route_day(van1["id"], coverage_zip="90016",
                                  service_date="2026-06-22T00:00:00Z",
                                  window_start="2026-06-22T09:00:00Z",
                                  window_end="2026-06-22T17:00:00Z")
        rd2 = fx.create_route_day(van2["id"], coverage_zip="90016",
                                  service_date="2026-06-22T00:00:00Z",
                                  window_start="2026-06-22T09:00:00Z",
                                  window_end="2026-06-22T17:00:00Z")
        petA = fx.create_pet(customer["id"], breed["id"], name="Brute", weight_lbs=50,
                             behavioral_flag="AGGRESSIVE")
        fx.upload_rabies(petA["id"], customer["id"])
        petB = fx.create_pet(customer["id"], breed["id"], name="Fang", weight_lbs=50,
                             behavioral_flag="AGGRESSIVE")
        fx.upload_rabies(petB["id"], customer["id"])
        aA = fx.create_appointment(petA["id"], tier["id"], customer["id"])
        fx.quote(aA["id"])
        fx.schedule(aA["id"], rd1["id"], "2026-06-22T09:00:00Z")  # [09:00,10:00) on the specialist
        aB = fx.create_appointment(petB["id"], tier["id"], customer["id"])
        fx.quote(aB["id"])
        # request [10:00,11:00) on a different van: raw back-to-back, groomer still free.
        scheduled = fx.schedule(aB["id"], rd2["id"], "2026-06-22T10:00:00Z")
        assert scheduled["status"] == "SCHEDULED", scheduled
        assert scheduled["groomer_id"] == spec["id"], scheduled
