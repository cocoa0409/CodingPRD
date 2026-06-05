"""Scheduling-time guards: validation precedence pairs, cross-entity state
blocks (suspended customer, locked route), boundary precision (route capacity
minute boundary, late-cancel 24h boundary), and resource overlap (buffered van
geometry, raw groomer geometry).

Difficulty queue: priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency, resource_temporal_overlap.
Corner queue: validations (van full, show-cut, zip), cross_cutting (OCC).
"""
from test_helpers import validate_error, validate_error_is_one_of, ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.constants import NONEXISTENT_UUID


class TestValidationPrecedence:
    def test_existence_beats_state_on_schedule(self, api):
        """PRD §3.4: "authentication is checked first, then authorization, then
        existence of referenced resources, then body well-formedness, then the
        appointment's state (ERR_INVALID_STATE)."
        PRD §2.9: "The first identifier that does not resolve causes the request to
        be rejected with ERR_NOT_FOUND (HTTP 404)."

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_schedule
        """
        fx.set_clock("2026-06-15T08:00:00Z")
        tier = fx.create_service_tier(code="FULL_GROOM", base_price_cents=6000,
                                      duration_multiplier=1.00)
        breed = fx.create_breed(base_service_minutes=45, coat_type="CURLY", size_class="SMALL")
        customer = fx.create_customer(service_zip="90009")
        pet = fx.create_pet(customer["id"], breed["id"], weight_lbs=20)
        fx.upload_rabies(pet["id"], customer["id"])
        appt = fx.create_appointment(pet["id"], tier["id"], customer["id"])  # REQUESTED, not quoted
        # Non-existent route day AND wrong state: existence (404) must win over state (409).
        resp = api.schedule_appointment(appt["id"], {
            "route_day_id": NONEXISTENT_UUID,
            "slot_start": "2026-06-15T09:30:00Z",
            "expected_route_day_version": 0,
        }, fx.DISPATCH)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_vaccination_beats_zip_on_schedule(self, api):
        """PRD §3.4: "then vaccination (ERR_VACCINATION_REQUIRED), then
        qualified-groomer existence (ERR_NO_QUALIFIED_GROOMER), then ZIP coverage
        (ERR_ZIP_NOT_COVERED)."

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
        # Vaccination valid at quote time, expires before schedule time.
        fx.upload_rabies(pet["id"], customer["id"],
                         issued_on="2025-01-01T00:00:00Z", expires_on="2026-06-20T00:00:00Z")
        appt = fx.create_appointment(pet["id"], tier["id"], customer["id"])
        fx.quote(appt["id"])
        # Route day ZIP deliberately mismatches the owner; window in late June.
        rd = fx.create_route_day(van["id"], coverage_zip="99999",
                                 service_date="2026-06-25T00:00:00Z",
                                 window_start="2026-06-25T09:00:00Z",
                                 window_end="2026-06-25T17:00:00Z")
        fx.set_clock("2026-06-25T08:00:00Z")  # now vaccination is expired
        resp = api.schedule_appointment(appt["id"], {
            "route_day_id": rd["id"],
            "slot_start": "2026-06-25T09:30:00Z",
            "expected_route_day_version": rd["version"],
        }, fx.DISPATCH)
        validate_error(resp, ApiErrorId.ERR_VACCINATION_REQUIRED.value)


class TestCrossEntityStateBlocks:
    def test_suspended_customer_cannot_schedule(self, api):
        """PRD §3.4: "The owning customer's account_status must be ACTIVE, not
        SUSPENDED, or ERR_ACCOUNT_SUSPENDED (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/schedule_blocked_by_suspended_customer
        """
        clock = "2026-06-19T10:00:00Z"
        fx.set_clock(clock)
        world = fx.setup_world(zip_code="90013", tier_code="FULL_GROOM",
                               base_price_cents=6000, duration_multiplier=1.00,
                               base_service_minutes=50, weight_lbs=40,
                               window_start="2026-06-19T09:00:00Z",
                               window_end="2026-06-19T17:00:00Z",
                               service_date="2026-06-19T00:00:00Z")
        # Drive 3 no-shows to suspend the account.
        fx.accrue_no_show_strikes(world, 3, first_slot="2026-06-19T09:00:00Z")
        cust = fx.get_customer(world["customer"]["id"])
        assert cust["account_status"] == "SUSPENDED", cust
        # A fresh quoted appointment cannot be scheduled.
        appt = fx.create_quoted_appointment(world)
        resp = api.schedule_appointment(appt["id"], {
            "route_day_id": world["route_day"]["id"],
            "slot_start": "2026-06-19T15:00:00Z",
            "expected_route_day_version": fx.current_route_version(world["route_day"]["id"]),
        }, fx.DISPATCH)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED.value)

    def test_locked_routeday_rejects_schedule(self, api):
        """PRD §3.4: "scheduling onto a LOCKED or CLOSED route day is rejected with
        ERR_ROUTE_LOCKED (HTTP 409)."
        PRD §3.7: "Once LOCKED, no new stops may be added — any attempt to schedule
        onto it is rejected with ERR_ROUTE_LOCKED."

        Design: Difficulty/cross_entity_state_dependency/schedule_blocked_by_locked_routeday
        """
        fx.set_clock("2026-06-20T08:00:00Z")
        world = fx.setup_world(zip_code="90014", tier_code="FULL_GROOM",
                               base_price_cents=6000, duration_multiplier=1.00,
                               base_service_minutes=50, weight_lbs=40,
                               window_start="2026-06-20T09:00:00Z",
                               window_end="2026-06-20T17:00:00Z",
                               service_date="2026-06-20T00:00:00Z")
        fx.create_groomer(handles_aggressive=True, skill_level="SENIOR")  # second groomer
        # First appointment scheduled, then dispatch to LOCK the route.
        fx.create_scheduled_appointment(world, "2026-06-20T09:30:00Z")
        fx.get_success_data(api.dispatch_route_day(world["route_day"]["id"], fx.DISPATCH))
        rd = fx.get_success_data(api.get_route_day(world["route_day"]["id"], fx.DISPATCH))
        assert rd["status"] == "LOCKED", rd
        # Second quoted appointment cannot schedule onto the locked route.
        appt2 = fx.create_quoted_appointment(world)
        resp = api.schedule_appointment(appt2["id"], {
            "route_day_id": world["route_day"]["id"],
            "slot_start": "2026-06-20T11:00:00Z",
            "expected_route_day_version": rd["version"],
        }, fx.DISPATCH)
        validate_error(resp, ApiErrorId.ERR_ROUTE_LOCKED.value)


class TestBoundaryPrecision:
    def test_route_capacity_inclusive_minute_boundary(self, api):
        """PRD §3.4: "Scheduling is permitted only when the existing load plus the
        new load is at most the window length in minutes; the boundary is inclusive,
        so exactly filling the window is allowed and one minute beyond is rejected
        with ERR_ROUTE_CAPACITY_EXCEEDED."

        Design: Difficulty/boundary_precision_check/route_capacity_exact_minute_boundary
        """
        fx.set_clock("2026-06-16T08:00:00Z")
        # 3h window = 180 min. First stop 100 min (load 115), second 50 min (load 65).
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
                                 window_end="2026-06-16T12:00:00Z")
        pet_big = fx.create_pet(customer["id"], breed130["id"], name="Big", weight_lbs=50)
        fx.upload_rabies(pet_big["id"], customer["id"])
        pet_small = fx.create_pet(customer["id"], breed50["id"], name="Small", weight_lbs=20)
        fx.upload_rabies(pet_small["id"], customer["id"])

        a_big = fx.create_appointment(pet_big["id"], tier130["id"], customer["id"])
        fx.quote(a_big["id"])
        fx.schedule(a_big["id"], rd["id"], "2026-06-16T09:00:00Z")  # [09:00,10:40), load 115

        a_small = fx.create_appointment(pet_small["id"], tier50["id"], customer["id"])
        fx.quote(a_small["id"])
        # second stop [10:55,11:45): no buffered overlap with [09:00,10:40); load 65.
        scheduled = fx.schedule(a_small["id"], rd["id"], "2026-06-16T10:55:00Z")
        assert scheduled["status"] == "SCHEDULED", scheduled  # 115+65 == 180, inclusive
        rd_after = fx.get_success_data(api.get_route_day(rd["id"], fx.DISPATCH))
        assert rd_after["booked_minutes"] == 180, rd_after

    def test_late_cancel_no_fee_at_exactly_24h(self, api):
        """PRD §3.5: "the server measures the whole-hour gap from the current clock
        to the reserved slot_start, taking the floor to whole hours. If that gap is
        at least 24 hours the cancellation is not late and there is no fee and no
        strike."

        Design: Difficulty/boundary_precision_check/late_cancel_hour_boundary_no_fee_at_exactly_24h
        """
        fx.set_clock("2026-06-17T09:00:00Z")
        world = fx.setup_world(zip_code="90012", tier_code="FULL_GROOM",
                               base_price_cents=6000, duration_multiplier=1.00,
                               base_service_minutes=50, weight_lbs=40,
                               window_start="2026-06-18T08:00:00Z",
                               window_end="2026-06-18T17:00:00Z",
                               service_date="2026-06-18T00:00:00Z")
        # slot_start exactly 24h after the clock (09:00 on the 17th -> 09:00 on the 18th).
        appt = fx.create_scheduled_appointment(world, "2026-06-18T09:00:00Z")
        cancelled = fx.cancel(appt["id"], world["customer"]["id"])
        assert cancelled["status"] == "CANCELLED", cancelled
        fees = fx.list_customer_fee_charges(world["customer"]["id"])
        assert fees == [], fees
        cust = fx.get_customer(world["customer"]["id"])
        assert cust["no_show_strikes"] == 0, cust


class TestResourceOverlap:
    def test_buffered_van_overlap_rejected(self, api):
        """PRD §3.4: "every other stop on the same route day whose status is
        RESERVED, SERVICED, or NO_SHOW is expanded by a 15-minute travel buffer on
        both ends — from 15 minutes before its slot_start to 15 minutes after its
        slot_end — and if the requested interval overlaps any such buffered interval,
        the request is rejected with ERR_SLOT_OVERLAP."

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
        fx.schedule(a70["id"], rd["id"], "2026-06-21T09:00:00Z")  # [09:00,10:10)

        a50 = fx.create_appointment(pet50["id"], tier50["id"], customer["id"])
        fx.quote(a50["id"])
        # request [10:20,11:10): raw does not touch, but buffered [08:45,10:25) does.
        resp = api.schedule_appointment(a50["id"], {
            "route_day_id": rd["id"],
            "slot_start": "2026-06-21T10:20:00Z",
            "expected_route_day_version": fx.current_route_version(rd["id"]),
        }, fx.DISPATCH)
        validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP.value)

    def test_groomer_double_booking_excludes_only_qualified(self, api):
        """PRD §3.4: "For the free-at-time test, a candidate groomer's own non-voided
        stops are compared using their raw [slot_start, slot_end) intervals with no
        travel buffer."
        PRD §3.4: "if the pool is empty, ERR_NO_QUALIFIED_GROOMER is raised."

        Design: Difficulty/resource_temporal_overlap/groomer_double_booking_excludes_only_qualified_groomer
        """
        fx.set_clock("2026-06-22T08:00:00Z")
        tier = fx.create_service_tier(code="FULL_GROOM", base_price_cents=6000,
                                      duration_multiplier=1.20)
        breed = fx.create_breed(base_service_minutes=50, coat_type="WIRE", size_class="LARGE")
        spec = fx.create_groomer(skill_level="SENIOR", handles_aggressive=True)
        fx.create_groomer(skill_level="JUNIOR", handles_aggressive=False)  # cannot handle aggressive
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
        # tier mult 1.20 * 50 = ceil(60) = 60 min -> [09:00,10:00)
        sched = fx.schedule(aA["id"], rd1["id"], "2026-06-22T09:00:00Z")
        assert sched["groomer_id"] == spec["id"], sched

        aB = fx.create_appointment(petB["id"], tier["id"], customer["id"])
        fx.quote(aB["id"])
        # request [09:30,10:30) on a DIFFERENT van so only the groomer overlap fires.
        resp = api.schedule_appointment(aB["id"], {
            "route_day_id": rd2["id"],
            "slot_start": "2026-06-22T09:30:00Z",
            "expected_route_day_version": rd2["version"],
        }, fx.DISPATCH)
        validate_error(resp, ApiErrorId.ERR_NO_QUALIFIED_GROOMER.value)


class TestOtherScheduleValidations:
    def test_van_stops_full_rejected(self, api):
        """PRD §3.4: "The number of stops on the route day must not exceed the van's
        max_stops, or ERR_VAN_STOPS_FULL (HTTP 409)."

        Design: Corner/validations/van_stops_full_rejected
        """
        fx.set_clock("2026-07-06T08:00:00Z")
        tier = fx.create_service_tier(code="BATH_ONLY", base_price_cents=3000,
                                      duration_multiplier=1.00)
        breed = fx.create_breed(base_service_minutes=30, coat_type="SMOOTH", size_class="SMALL")
        fx.create_groomer(handles_aggressive=True, skill_level="SENIOR")
        fx.create_groomer(handles_aggressive=True, skill_level="SENIOR")
        van = fx.create_van(max_stops=1)
        customer = fx.create_customer(service_zip="10015")
        rd = fx.create_route_day(van["id"], coverage_zip="10015",
                                 service_date="2026-07-06T00:00:00Z",
                                 window_start="2026-07-06T09:00:00Z",
                                 window_end="2026-07-06T17:00:00Z")
        pet1 = fx.create_pet(customer["id"], breed["id"], name="A1", weight_lbs=15)
        fx.upload_rabies(pet1["id"], customer["id"])
        pet2 = fx.create_pet(customer["id"], breed["id"], name="A2", weight_lbs=15)
        fx.upload_rabies(pet2["id"], customer["id"])
        a1 = fx.create_appointment(pet1["id"], tier["id"], customer["id"])
        fx.quote(a1["id"])
        fx.schedule(a1["id"], rd["id"], "2026-07-06T09:00:00Z")
        a2 = fx.create_appointment(pet2["id"], tier["id"], customer["id"])
        fx.quote(a2["id"])
        # second stop fits the window but exceeds max_stops 1.
        resp = api.schedule_appointment(a2["id"], {
            "route_day_id": rd["id"],
            "slot_start": "2026-07-06T12:00:00Z",
            "expected_route_day_version": fx.current_route_version(rd["id"]),
        }, fx.DISPATCH)
        validate_error(resp, ApiErrorId.ERR_VAN_STOPS_FULL.value)

    def test_show_cut_unsupported_van_rejected(self, api):
        """PRD §3.4: "when the requested tier's code is SHOW_CUT, the assigned van
        must have has_show_equipment true and a SENIOR groomer must be available in
        the pool, or the request is rejected with ERR_SHOW_CUT_UNSUPPORTED (HTTP 422)."

        Design: Corner/validations/show_cut_unsupported_van_rejected
        """
        fx.set_clock("2026-07-07T08:00:00Z")
        world = fx.setup_world(zip_code="10016", tier_code="SHOW_CUT",
                               base_price_cents=18000, duration_multiplier=2.00,
                               base_service_minutes=50, weight_lbs=30,
                               has_show_equipment=False, skill_level="SENIOR",
                               window_start="2026-07-07T09:00:00Z",
                               window_end="2026-07-07T17:00:00Z",
                               service_date="2026-07-07T00:00:00Z")
        appt = fx.create_quoted_appointment(world)
        resp = api.schedule_appointment(appt["id"], {
            "route_day_id": world["route_day"]["id"],
            "slot_start": "2026-07-07T09:30:00Z",
            "expected_route_day_version": world["rd_version"],
        }, fx.DISPATCH)
        validate_error(resp, ApiErrorId.ERR_SHOW_CUT_UNSUPPORTED.value)

    def test_zip_not_covered_rejected(self, api):
        """PRD §3.4: "The route day's coverage_zip must equal the owning customer's
        service_zip, otherwise ERR_ZIP_NOT_COVERED (HTTP 422)."

        Design: Corner/validations/zip_not_covered_rejected
        """
        fx.set_clock("2026-07-08T08:00:00Z")
        tier = fx.create_service_tier(code="FULL_GROOM", base_price_cents=6000,
                                      duration_multiplier=1.00)
        breed = fx.create_breed(base_service_minutes=50, coat_type="CURLY", size_class="MEDIUM")
        fx.create_groomer(handles_aggressive=True, skill_level="SENIOR")
        van = fx.create_van(max_stops=5)
        customer = fx.create_customer(service_zip="10017")
        pet = fx.create_pet(customer["id"], breed["id"], weight_lbs=30)
        fx.upload_rabies(pet["id"], customer["id"])
        rd = fx.create_route_day(van["id"], coverage_zip="20020",  # mismatched
                                 service_date="2026-07-08T00:00:00Z",
                                 window_start="2026-07-08T09:00:00Z",
                                 window_end="2026-07-08T17:00:00Z")
        appt = fx.create_appointment(pet["id"], tier["id"], customer["id"])
        fx.quote(appt["id"])
        resp = api.schedule_appointment(appt["id"], {
            "route_day_id": rd["id"],
            "slot_start": "2026-07-08T09:30:00Z",
            "expected_route_day_version": rd["version"],
        }, fx.DISPATCH)
        validate_error(resp, ApiErrorId.ERR_ZIP_NOT_COVERED.value)


class TestOptimisticConcurrency:
    def test_stale_route_version_rejected(self, api):
        """PRD §2.8: "If they do not match — because a prior schedule legitimately
        created a stop and recomputed booked_minutes, advancing the route day's
        version since the client last read it — the request is rejected with
        ERR_STALE_ROUTE_VERSION (HTTP 412) before any window, overlap, or capacity
        check runs."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_route_version_on_schedule
        """
        fx.set_clock("2026-07-12T08:00:00Z")
        tier = fx.create_service_tier(code="BATH_ONLY", base_price_cents=3000,
                                      duration_multiplier=1.00)
        breed = fx.create_breed(base_service_minutes=30, coat_type="SMOOTH", size_class="SMALL")
        fx.create_groomer(handles_aggressive=True, skill_level="SENIOR")
        fx.create_groomer(handles_aggressive=True, skill_level="SENIOR")
        van = fx.create_van(max_stops=5)
        customer = fx.create_customer(service_zip="10025")
        rd = fx.create_route_day(van["id"], coverage_zip="10025",
                                 service_date="2026-07-12T00:00:00Z",
                                 window_start="2026-07-12T09:00:00Z",
                                 window_end="2026-07-12T17:00:00Z")
        rd_v0 = rd["version"]
        pet1 = fx.create_pet(customer["id"], breed["id"], name="M1", weight_lbs=15)
        fx.upload_rabies(pet1["id"], customer["id"])
        pet2 = fx.create_pet(customer["id"], breed["id"], name="M2", weight_lbs=15)
        fx.upload_rabies(pet2["id"], customer["id"])
        a1 = fx.create_appointment(pet1["id"], tier["id"], customer["id"])
        fx.quote(a1["id"])
        a2 = fx.create_appointment(pet2["id"], tier["id"], customer["id"])
        fx.quote(a2["id"])
        fx.schedule(a1["id"], rd["id"], "2026-07-12T09:00:00Z", expected_version=rd_v0)
        # second still carrying rd_v0, now stale.
        resp = api.schedule_appointment(a2["id"], {
            "route_day_id": rd["id"],
            "slot_start": "2026-07-12T11:00:00Z",
            "expected_route_day_version": rd_v0,
        }, fx.DISPATCH)
        validate_error(resp, ApiErrorId.ERR_STALE_ROUTE_VERSION.value)

    def test_fresh_route_version_succeeds(self, api):
        """PRD §2.4: "The version begins at its initial value when the resource is
        created and increments by one on every mutation."
        PRD §2.8: "The server compares it to the target route day's current version."

        Design: Corner/cross_cutting_complexity_layers/occ_fresh_route_version_succeeds
        """
        fx.set_clock("2026-07-13T08:00:00Z")
        tier = fx.create_service_tier(code="BATH_ONLY", base_price_cents=3000,
                                      duration_multiplier=1.00)
        breed = fx.create_breed(base_service_minutes=30, coat_type="SMOOTH", size_class="SMALL")
        fx.create_groomer(handles_aggressive=True, skill_level="SENIOR")
        fx.create_groomer(handles_aggressive=True, skill_level="SENIOR")
        van = fx.create_van(max_stops=5)
        customer = fx.create_customer(service_zip="10026")
        rd = fx.create_route_day(van["id"], coverage_zip="10026",
                                 service_date="2026-07-13T00:00:00Z",
                                 window_start="2026-07-13T09:00:00Z",
                                 window_end="2026-07-13T17:00:00Z")
        rd_v0 = rd["version"]
        pet1 = fx.create_pet(customer["id"], breed["id"], name="N1", weight_lbs=15)
        fx.upload_rabies(pet1["id"], customer["id"])
        pet2 = fx.create_pet(customer["id"], breed["id"], name="N2", weight_lbs=15)
        fx.upload_rabies(pet2["id"], customer["id"])
        a1 = fx.create_appointment(pet1["id"], tier["id"], customer["id"])
        fx.quote(a1["id"])
        a2 = fx.create_appointment(pet2["id"], tier["id"], customer["id"])
        fx.quote(a2["id"])
        fx.schedule(a1["id"], rd["id"], "2026-07-13T09:00:00Z", expected_version=rd_v0)
        rd_v1 = fx.current_route_version(rd["id"])
        scheduled = fx.schedule(a2["id"], rd["id"], "2026-07-13T11:00:00Z", expected_version=rd_v1)
        assert scheduled["status"] == "SCHEDULED", scheduled
        rd_after = fx.get_success_data(api.get_route_day(rd["id"], fx.DISPATCH))
        assert rd_after["version"] == rd_v0 + 2, rd_after
