"""Pet profiles, holiday demand windows, and their listing filters (PRD §3.2, §3.3)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_pet_profile_payload, create_holiday_window_payload,
    make_member_headers,
    bootstrap_founders, create_applicant, create_pet, create_window,
    ADMIN,
)


class TestPetProfiles:
    def test_pet_profile_creation_system_fields(self, api):
        """PRD §3.2: "The creating member becomes the profile's `owner_member_id`,
        and the profile starts with `active` set to true."
        PRD §2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the
        acting Member; ownership checks on any resource that references a Member —
        for example a sitting request's `owner_member_id`, a claim's
        `claimer_member_id`, an assignment's `sitter_member_id`, a reference's
        `referee_member_id`, or a dispute's `mediator_member_id` — compare that
        foreign-key field to `X-User-ID`."

        Design: Corner/entities/pet_profile_creation_system_fields
        """
        f = bootstrap_founders()
        res = api.create_pet_profile(f["f1"]["id"], create_pet_profile_payload(
            pet_name="Biscuit", species="DOG"), make_member_headers(f["f1"]["id"]))
        pet = validate_success(res, 201)
        assert pet["owner_member_id"] == f["f1"]["id"]
        assert pet["active"] is True
        assert pet["species"] == "DOG"

        fetched = validate_success(api.get_pet_profile(pet["id"], ADMIN), 200)
        assert fetched["routine_notes"] == "Feed twice daily, walk morning."
        assert fetched["medical_notes"] == "No medications."
        assert fetched["emergency_vet_name"] == "Maple Vet Clinic"
        assert fetched["emergency_vet_phone"] == "+15550911"
        assert fetched["emergency_vet_address"] == "12 Maple St"

    def test_pet_profile_invalid_species_rejected(self, api):
        """PRD §3.2: "A member creates a pet profile with the pet's `pet_name`, its
        `species` — one of `DOG`, `CAT`, `BIRD`, `RABBIT`, or `OTHER` — ..."
        PRD §3.3: "violations are rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/pet_profile_invalid_enum_species_returns_400
        """
        x = create_applicant("Pet Owner", "owner@coop.test", "+15550304")
        res = api.create_pet_profile(x["id"], create_pet_profile_payload(
            pet_name="Rex", species="DINOSAUR", routine_notes="Roam free."),
            make_member_headers(x["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        data = get_success_data(api.list_pet_profiles(x["id"], ADMIN))
        assert data == [], f"Expected no pet profiles persisted, got {data}"

    def test_pet_profiles_active_filter_after_deactivate(self, api):
        """PRD §3.2: "Deactivating a profile — permitted only to its owner, with
        anyone else rejected as `ERR_FORBIDDEN` — sets `active` to false, which
        hides the pet from new requests while preserving its history. The
        pet-profile listing can be filtered by `active`."

        Design: Corner/endpoints/pet_profiles_active_filter_after_deactivate
        """
        f = bootstrap_founders()
        pet1 = create_pet(f["f1"])
        pet_old = create_pet(f["f1"], pet_name="OldBoy", species="DOG",
                             routine_notes="Senior dog, slow walks.",
                             medical_notes="Joint supplements.")
        get_success_data(api.deactivate_pet_profile(pet_old["id"], make_member_headers(f["f1"]["id"])))

        active = get_success_data(api.list_pet_profiles(f["f1"]["id"], ADMIN, params={"active": "true"}))
        assert [p["id"] for p in active] == [pet1["id"]]
        inactive = get_success_data(api.list_pet_profiles(f["f1"]["id"], ADMIN, params={"active": "false"}))
        assert [p["id"] for p in inactive] == [pet_old["id"]]

        fetched = validate_success(api.get_pet_profile(pet_old["id"], ADMIN), 200)
        assert fetched["active"] is False


class TestHolidayWindows:
    def test_holiday_window_enabled_defaults_true(self, api):
        """PRD §3.3: "An administrator defines a holiday window with a `name` (for
        example "Thanksgiving 2026"), an inclusive `window_start`, an exclusive
        `window_end`, and a `demand_multiplier` between 1.0 and 3.0; the `enabled`
        flag defaults to true."

        Design: Corner/entities/holiday_window_enabled_default_true
        """
        res = api.create_holiday_window(create_holiday_window_payload(
            name="Labor Day", window_start="2026-09-07T00:00:00Z",
            window_end="2026-09-08T00:00:00Z", demand_multiplier=1.5), ADMIN)
        window = validate_success(res, 201)
        assert window["enabled"] is True

        data = get_success_data(api.list_holiday_windows(ADMIN, params={"enabled": "true"}))
        assert window["id"] in [w["id"] for w in data]

    def test_holiday_window_multiplier_range(self, api):
        """PRD §3.3: "An administrator defines a holiday window with a `name` (for
        example "Thanksgiving 2026"), an inclusive `window_start`, an exclusive
        `window_end`, and a `demand_multiplier` between 1.0 and 3.0; the `enabled`
        flag defaults to true."
        PRD §3.3: "violations are rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/holiday_window_multiplier_out_of_range_returns_400
        """
        res = api.create_holiday_window(create_holiday_window_payload(
            name="TooHot", demand_multiplier=3.5), ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        ok = api.create_holiday_window(create_holiday_window_payload(
            name="MaxOK", demand_multiplier=3.0), ADMIN)
        window = validate_success(ok, 201)
        assert window["demand_multiplier"] == pytest.approx(3.0, abs=0.001)

    def test_holiday_windows_enabled_filter(self, api):
        """PRD §3.3: "Disabling a window simply sets `enabled` to false and never
        reprices offers that were already computed — once an offer is locked at
        posting it stays locked."
        PRD §2.3: "Several collections support equality filters beyond pagination,
        each named after the field it matches: ... holiday windows filter by
        `enabled`; ..."

        Design: Corner/endpoints/holiday_windows_enabled_filter
        """
        w1 = create_window(name="W1", demand_multiplier=2.0)
        w2 = create_window(name="W2", window_start="2026-12-31T00:00:00Z",
                           window_end="2027-01-02T00:00:00Z", demand_multiplier=2.5)
        get_success_data(api.disable_holiday_window(w2["id"], ADMIN))

        enabled = get_success_data(api.list_holiday_windows(ADMIN, params={"enabled": "true"}))
        assert [w["id"] for w in enabled] == [w1["id"]]
        disabled = get_success_data(api.list_holiday_windows(ADMIN, params={"enabled": "false"}))
        assert [w["id"] for w in disabled] == [w2["id"]]

    def test_credit_locked_after_window_disable(self, api):
        """PRD §3.3: "Disabling a window simply sets `enabled` to false and never
        reprices offers that were already computed — once an offer is locked at
        posting it stays locked."

        Design: Corner/calculations/credit_hours_offered_locked_after_window_disable
        """
        from test_helpers import post_request
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        window = create_window(name="PreThanks", window_start="2026-11-20T00:00:00Z",
                               window_end="2026-11-22T00:00:00Z", demand_multiplier=2.0)
        request = post_request(f["f1"], pet, start_at="2026-11-21T10:00:00Z",
                               end_at="2026-11-21T14:00:00Z", instructions="Lock-in sit")
        assert request["credit_hours_offered"] == pytest.approx(8.0, abs=0.001)

        get_success_data(api.disable_holiday_window(window["id"], ADMIN))
        after = validate_success(api.get_sitting_request(request["id"], ADMIN), 200)
        assert after["credit_hours_offered"] == pytest.approx(8.0, abs=0.001), (
            "Disabling the window must not reprice the locked offer")
        refreshed = validate_success(api.get_holiday_window(window["id"], ADMIN), 200)
        assert refreshed["enabled"] is False

    def test_disabled_window_excluded_from_pricing(self, api):
        """PRD §3.3: "The system then considers every enabled holiday window whose
        interval intersects the requested interval — meaning the window starts
        before the request ends and ends after the request starts — and takes the
        single highest `demand_multiplier` among them; multipliers never compound,
        and when no enabled window intersects, the multiplier is 1.0."

        Design: Corner/calculations/disabled_window_excluded_from_input_set
        """
        from test_helpers import post_request
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        create_window(name="Ghost", window_start="2026-12-25T00:00:00Z",
                      window_end="2026-12-26T00:00:00Z", demand_multiplier=2.5,
                      enabled=False)
        request = post_request(f["f1"], pet, start_at="2026-12-25T10:00:00Z",
                               end_at="2026-12-25T14:00:00Z", instructions="Disabled-window sit")
        assert request["credit_hours_offered"] == pytest.approx(4.0, abs=0.001)

    def test_holiday_window_edge_touch_exclusion(self, api):
        """PRD §3.3: "The system then considers every enabled holiday window whose
        interval intersects the requested interval — meaning the window starts
        before the request ends and ends after the request starts — and takes the
        single highest `demand_multiplier` among them; multipliers never compound,
        and when no enabled window intersects, the multiplier is 1.0."
        PRD §2.6: "Wherever this document speaks of a time interval belonging to a
        request, an assignment, or a holiday window, the interval is half-open: it
        includes its start instant and excludes its end instant."

        Design: Difficulty/resource_temporal_overlap/holiday_window_edge_touch_exclusion
        """
        from test_helpers import post_request
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        create_window(name="ChristmasDay", window_start="2026-12-25T00:00:00Z",
                      window_end="2026-12-26T00:00:00Z", demand_multiplier=2.0)
        # Sit starting exactly at window_end touches the exclusive end: no intersection.
        edge = post_request(f["f1"], pet, start_at="2026-12-26T00:00:00Z",
                            end_at="2026-12-26T04:00:00Z", instructions="Edge-touch sit")
        assert edge["credit_hours_offered"] == pytest.approx(4.0, abs=0.001)
        # Sit starting one hour before window_end intersects by an hour: 2.0 applies.
        inside = post_request(f["f1"], pet, start_at="2026-12-25T23:00:00Z",
                              end_at="2026-12-26T03:00:00Z", instructions="Intersecting sit")
        assert inside["credit_hours_offered"] == pytest.approx(8.0, abs=0.001)

    def test_holiday_window_intersection_one_hour(self, api):
        """PRD §3.3: "The offer is the duration multiplied by that multiplier,
        rounded half-up to 2 decimal places."
        PRD §2.6: "Wherever this document speaks of a time interval belonging to a
        request, an assignment, or a holiday window, the interval is half-open: it
        includes its start instant and excludes its end instant."

        Design: Difficulty/resource_temporal_overlap/holiday_window_edge_touch_exclusion
        """
        from test_helpers import post_request
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        create_window(name="ChristmasDay", window_start="2026-12-25T00:00:00Z",
                      window_end="2026-12-26T00:00:00Z", demand_multiplier=2.0)
        inside = post_request(f["f1"], pet, start_at="2026-12-25T23:00:00Z",
                              end_at="2026-12-26T03:00:00Z", instructions="Intersecting sit")
        assert inside["status"] == "OPEN"
        assert inside["credit_hours_offered"] == pytest.approx(8.0, abs=0.001)
