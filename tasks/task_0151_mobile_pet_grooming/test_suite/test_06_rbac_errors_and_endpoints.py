"""RBAC enforcement, auth/validation errors, derived-field reconciliation on
upload, the calm-add-on rule, endpoint-level conditional actions and filtered
listing, and immediate-consistency on schedule.

Corner queue: validations (addon calm), endpoints, errors, rbac,
cross_cutting_complexity_layers (derived vaccination flip), consistency_model.
"""
from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client


class TestAddOnCalmRule:
    def test_requires_calm_addon_rejected_for_aggressive_pet(self, api):
        """PRD §3.6: "If the add-on's requires_calm flag is true and the
        appointment's pet has a behavioral_flag of AGGRESSIVE, the attachment is
        rejected with ERR_ADDON_NOT_ALLOWED (HTTP 422), because a calm-requiring
        service cannot be performed on an aggressive animal."

        Design: Corner/validations/addon_requires_calm_rejected_for_aggressive_pet
        """
        tier = fx.create_service_tier(code="FULL_GROOM", base_price_cents=6000,
                                      duration_multiplier=1.00)
        breed = fx.create_breed(base_service_minutes=55, size_class="LARGE")
        addon = fx.create_add_on(code="TEETH_CLEAN", price_cents=1500,
                                 duration_minutes=15, requires_calm=True)
        customer = fx.create_customer(service_zip="10014")
        pet = fx.create_pet(customer["id"], breed["id"], name="Bruno",
                            weight_lbs=60, behavioral_flag="AGGRESSIVE")
        appt = fx.create_appointment(pet["id"], tier["id"], customer["id"])
        resp = api.attach_add_on(appt["id"], {"add_on_id": addon["id"]},
                                 fx.make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_ADDON_NOT_ALLOWED.value)


class TestEndpointActions:
    def test_dispatch_without_reserved_stops_invalid_state(self, api):
        """PRD §3.7: "A dispatcher dispatches a route day to lock it, advancing it
        from OPEN to LOCKED; this requires that at least one stop on the day is in
        RESERVED status."

        Design: Corner/endpoints/dispatch_with_no_reserved_stops_invalid_state
        """
        van = fx.create_van(max_stops=5)
        rd = fx.create_route_day(van["id"], coverage_zip="10018",
                                 service_date="2026-07-09T00:00:00Z",
                                 window_start="2026-07-09T09:00:00Z",
                                 window_end="2026-07-09T17:00:00Z")
        resp = api.dispatch_route_day(rd["id"], fx.DISPATCH)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_list_route_days_filtered_by_van(self, api):
        """PRD §4: "GET /route-days | List route days, filterable by van."
        PRD §2.3: "List results are always sorted by created_at in ascending order."

        Design: Corner/endpoints/list_route_days_filtered_by_van
        """
        van1 = fx.create_van(max_stops=5)
        van2 = fx.create_van(max_stops=5)
        rd1 = fx.create_route_day(van1["id"], coverage_zip="10019",
                                  service_date="2026-07-10T00:00:00Z",
                                  window_start="2026-07-10T09:00:00Z",
                                  window_end="2026-07-10T17:00:00Z")
        rd2 = fx.create_route_day(van2["id"], coverage_zip="10019",
                                  service_date="2026-07-10T00:00:00Z",
                                  window_start="2026-07-10T09:00:00Z",
                                  window_end="2026-07-10T17:00:00Z")
        resp = api.list_route_days(fx.DISPATCH, params={"van_id": van1["id"]})
        from test_helpers import validate_paginated
        data, _ = validate_paginated(resp)
        ids = {r["id"] for r in data}
        assert rd1["id"] in ids, data
        assert rd2["id"] not in ids, data


class TestAuthAndValidationErrors:
    def test_missing_headers_unauthenticated(self, api):
        """PRD §2.1: "If either header is missing or malformed, the request is
        rejected with ERR_UNAUTHENTICATED (HTTP 401) before any other processing."

        Design: Corner/errors/error_unauthenticated_missing_headers
        """
        resp = api_client.raw("POST", "/breeds", payload={
            "name": "X", "coat_type": "SMOOTH",
            "size_class": "MEDIUM", "base_service_minutes": 60,
        }, headers={"Content-Type": "application/json"})  # no auth headers
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_vaccination_expires_before_issued_validation(self, api):
        """PRD §3.2: "The expires_on value must be strictly later than issued_on; a
        record that violates this ordering is rejected with ERR_VALIDATION (HTTP 422)."

        Design: Corner/errors/error_validation_expires_before_issued
        """
        breed = fx.create_breed(base_service_minutes=50)
        customer = fx.create_customer(service_zip="10020")
        pet = fx.create_pet(customer["id"], breed["id"], name="Blue", weight_lbs=30)
        resp = api.create_vaccination(pet["id"], {
            "vaccine_type": "RABIES",
            "issued_on": "2026-06-01T00:00:00Z",
            "expires_on": "2026-05-01T00:00:00Z",
        }, fx.make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


class TestRbac:
    def test_customer_cannot_quote(self, api):
        """PRD §2.1: "If the headers are well-formed but the declared role is not
        permitted to invoke the requested operation ... the request is rejected with
        ERR_FORBIDDEN (HTTP 403)."
        PRD §4: "POST /appointments/{id}/quote | Issue or re-issue a quote ...
        | Dispatcher."

        Design: Corner/rbac/customer_cannot_quote_appointment
        """
        tier = fx.create_service_tier(code="FULL_GROOM", base_price_cents=6000,
                                      duration_multiplier=1.00)
        breed = fx.create_breed(base_service_minutes=50)
        customer = fx.create_customer(service_zip="10021")
        pet = fx.create_pet(customer["id"], breed["id"], name="Kel", weight_lbs=30)
        appt = fx.create_appointment(pet["id"], tier["id"], customer["id"])
        resp = api.quote_appointment(appt["id"], fx.make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_customer_cannot_cancel_other_customers_appointment(self, api):
        """PRD §2.1: "an ownership-scoped role attempts to act on a resource it does
        not own — the request is rejected with ERR_FORBIDDEN (HTTP 403)."
        PRD §3.5: "Only the owning customer may cancel; an attempt by another
        customer is forbidden."

        Design: Corner/rbac/customer_cannot_cancel_other_customers_appointment
        """
        tier = fx.create_service_tier(code="FULL_GROOM", base_price_cents=6000,
                                      duration_multiplier=1.00)
        breed = fx.create_breed(base_service_minutes=60, coat_type="CURLY", size_class="LARGE")
        owner = fx.create_customer(service_zip="10022", email="owner-rbac@x.com")
        intruder = fx.create_customer(service_zip="10023", email="intruder-rbac@x.com")
        pet = fx.create_pet(owner["id"], breed["id"], name="Zoi", weight_lbs=40)
        appt = fx.create_appointment(pet["id"], tier["id"], owner["id"])
        resp = api.cancel_appointment(appt["id"], fx.make_customer_headers(intruder["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_groomer_cannot_complete_unassigned_appointment(self, api):
        """PRD §2.1: "a groomer may complete only an appointment whose groomer_id
        equals their own id."
        PRD §3.5: "Only the groomer whose id equals the appointment's groomer_id may
        complete it."

        Design: Corner/rbac/groomer_cannot_complete_unassigned_appointment
        """
        fx.set_clock("2026-07-11T08:00:00Z")
        tier = fx.create_service_tier(code="FULL_GROOM", base_price_cents=6000,
                                      duration_multiplier=1.00)
        breed = fx.create_breed(base_service_minutes=50)
        gA = fx.create_groomer(skill_level="SENIOR", handles_aggressive=True,
                               status="AVAILABLE", email="ga-rbac@x.com")
        gB = fx.create_groomer(skill_level="SENIOR", handles_aggressive=True,
                               status="OFF_DUTY", email="gb-rbac@x.com")
        van = fx.create_van(max_stops=5)
        customer = fx.create_customer(service_zip="10024")
        pet = fx.create_pet(customer["id"], breed["id"], name="Sal", weight_lbs=30)
        fx.upload_rabies(pet["id"], customer["id"])
        rd = fx.create_route_day(van["id"], coverage_zip="10024",
                                 service_date="2026-07-11T00:00:00Z",
                                 window_start="2026-07-11T09:00:00Z",
                                 window_end="2026-07-11T17:00:00Z")
        appt = fx.create_appointment(pet["id"], tier["id"], customer["id"])
        fx.quote(appt["id"])
        scheduled = fx.schedule(appt["id"], rd["id"], "2026-07-11T09:30:00Z")
        assert scheduled["groomer_id"] == gA["id"], scheduled  # only AVAILABLE candidate
        resp = api.complete_appointment(appt["id"], {}, fx.make_groomer_headers(gB["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestDerivedAndConsistency:
    def test_vaccination_status_flips_valid_on_upload(self, api):
        """PRD §2.6: "vaccination_status is derived to be VALID when the pet has at
        least one RABIES vaccination record that has not expired relative to the
        current clock, and EXPIRED otherwise; it is recomputed whenever a vaccination
        record is uploaded."

        Design: Corner/cross_cutting_complexity_layers/derived_vaccination_status_flips_valid_on_upload
        """
        fx.set_clock("2026-07-14T08:00:00Z")
        breed = fx.create_breed(base_service_minutes=40, coat_type="DOUBLE", size_class="SMALL")
        customer = fx.create_customer(service_zip="10027")
        pet = fx.create_pet(customer["id"], breed["id"], name="Val", weight_lbs=25)
        assert pet["vaccination_status"] == "EXPIRED", pet
        fx.upload_rabies(pet["id"], customer["id"],
                         issued_on="2026-01-01T00:00:00Z", expires_on="2027-01-01T00:00:00Z")
        refreshed = fx.get_success_data(api.get_pet(pet["id"], fx.make_customer_headers(customer["id"])))
        assert refreshed["vaccination_status"] == "VALID", refreshed

    def test_schedule_response_immediately_populated(self, api):
        """PRD §3.4: "it sets the appointment's route_stop_id to the new stop and its
        groomer_id to the selected groomer."

        Design: Corner/consistency_model/schedule_response_reflects_all_changes_immediately
        """
        fx.set_clock("2026-07-16T08:00:00Z")
        world = fx.setup_world(zip_code="10029", tier_code="FULL_GROOM",
                               base_price_cents=6000, duration_multiplier=1.00,
                               base_service_minutes=45, weight_lbs=22,
                               window_start="2026-07-16T09:00:00Z",
                               window_end="2026-07-16T17:00:00Z",
                               service_date="2026-07-16T00:00:00Z")
        appt = fx.create_quoted_appointment(world)
        resp = api.schedule_appointment(appt["id"], {
            "route_day_id": world["route_day"]["id"],
            "slot_start": "2026-07-16T09:30:00Z",
            "expected_route_day_version": world["rd_version"],
        }, fx.DISPATCH)
        data = validate_success(resp, 200)
        assert data["status"] == "SCHEDULED", data
        assert data["route_stop_id"], data
        assert data["groomer_id"] == world["groomer"]["id"], data
