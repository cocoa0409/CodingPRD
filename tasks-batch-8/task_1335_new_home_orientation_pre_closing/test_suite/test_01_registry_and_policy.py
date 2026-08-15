"""Community policy defaults, registries, and home creation basics."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_home,
    get_success_data,
    is_valid_uuid,
    make_rep_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import (
    create_appointment_payload,
    create_home_payload,
    create_homebuyer_payload,
)


class TestCommunityPolicyDefaults:
    def test_community_defaults_applied_and_trend_readable(self, api, manager_headers):
        """PRD §3.1: "A `CustomerCareManager` creates one with a `name` and, optionally,
        overrides for its policy knobs: `holdback_cost_multiplier` (default 1.5),
        `holdback_min_cents` (default 50000), `holdback_max_cents` (default 1000000),
        `orientation_min_days_before_closing` (default 5),
        `orientation_max_days_before_closing` (default 30),
        `appointment_duration_minutes` (default 120), `appointment_buffer_minutes`
        (default 30), `survey_window_days` (default 14), and
        `cosmetic_photo_required` (default true)."
        PRD §3.8: "Quality rolls up per community and calendar month. ... The
        response echoes `period_month` and reports `submitted_survey_count`, the
        number of those surveys"

        Design: Corner/entities/community_policy_defaults_applied
        """
        community = fx.setup_community()  # only `name` supplied
        assert community["holdback_cost_multiplier"] == 1.5, (
            f"default multiplier must be 1.5, got {community['holdback_cost_multiplier']}"
        )
        assert community["orientation_min_days_before_closing"] == 5, (
            f"default min days must be 5, got {community['orientation_min_days_before_closing']}"
        )
        assert community["cosmetic_photo_required"] is True, (
            f"default photo flag must be true, got {community['cosmetic_photo_required']}"
        )
        resp = api.get_quality_trend(community["id"], manager_headers,
                                     params={"period_month": "2026-08"})
        trend = validate_success(resp)
        assert trend["submitted_survey_count"] == 0, (
            f"new community has no submitted surveys, got {trend['submitted_survey_count']}"
        )

    def test_community_all_policy_knob_defaults(self, api, manager_headers):
        """PRD §3.1: "A `CustomerCareManager` creates one with a `name` and, optionally,
        overrides for its policy knobs: `holdback_cost_multiplier` (default 1.5),
        `holdback_min_cents` (default 50000), `holdback_max_cents` (default 1000000),
        `orientation_min_days_before_closing` (default 5),
        `orientation_max_days_before_closing` (default 30),
        `appointment_duration_minutes` (default 120), `appointment_buffer_minutes`
        (default 30), `survey_window_days` (default 14), and
        `cosmetic_photo_required` (default true)."

        Design: Corner/entities/community_policy_defaults_applied
        """
        community = fx.setup_community()
        assert community["holdback_min_cents"] == 50_000
        assert community["holdback_max_cents"] == 1_000_000
        assert community["orientation_max_days_before_closing"] == 30
        assert community["appointment_duration_minutes"] == 120
        assert community["appointment_buffer_minutes"] == 30
        assert community["survey_window_days"] == 14


class TestHomebuyerRegistry:
    def test_duplicate_email_rejected(self, api, manager_headers):
        """PRD §3.1: "A `CustomerCareManager` registers a **Homebuyer** with
        `full_name`, `email`, and an optional `phone`; the email must be unique
        across homebuyers, and a duplicate is rejected with `ERR_DUPLICATE_EMAIL`."

        Design: Corner/entities/homebuyer_duplicate_email_rejected
        """
        fx.setup_buyer(email="alice@example.com")
        resp = api.create_homebuyer(
            create_homebuyer_payload(full_name="Alice Again", email="alice@example.com"),
            manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL)


class TestHomeCreation:
    def test_home_missing_closing_date_rejected(self, api, manager_headers):
        """PRD §2.8: "Request schema — required fields are present, types and enum
        members are valid, and ratings lie within their 1-to-5 range; otherwise
        `ERR_VALIDATION` (HTTP 400)."
        PRD §3.1: "A `CustomerCareManager` then brings a **Home** under care by
        supplying `community_id`, `primary_buyer_id`, `lot_number`, `address`,
        `sales_price_cents`, and `closing_date`."

        Design: Corner/entities/home_create_missing_required_closing_date
        """
        community, buyer, _rep = fx.setup_base()
        resp = api.create_home(
            {
                "community_id": community["id"],
                "primary_buyer_id": buyer["id"],
                "lot_number": "L-101",
                "address": "1 Riverbend Way",
                "sales_price_cents": 45_000_000,
            },
            manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_home_create_ignores_client_supplied_id_and_version(self, api, manager_headers):
        """PRD §2.5: "`id` (string): a server-minted unique identifier formatted as a
        UUID, with no type prefix."
        PRD §2.5: "`version` (integer): a system-managed integer that increments by
        one on every mutation"

        Design: Corner/entities/home_create_system_fields_input_ignored
        """
        community, buyer, _rep = fx.setup_base()
        client_id = "00000000-0000-4000-8000-aaaaaaaaaaaa"
        payload = create_home_payload(
            community_id=community["id"], primary_buyer_id=buyer["id"]
        )
        payload["id"] = client_id
        payload["version"] = 99
        resp = api.create_home(payload, manager_headers)
        home = validate_success(resp, expected_status=201)
        assert home["version"] == 1, f"version must start at 1, got {home['version']}"
        assert home["id"] != client_id, "server must mint its own id"
        assert is_valid_uuid(home["id"])
        assert_home(home)

    def test_get_home_not_found(self, api, manager_headers):
        """PRD §2.8: "Path existence — every identifier in the URL resolves to an
        existing resource; otherwise `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_home_not_found_returns_404
        """
        resp = api.get_home(NON_EXISTENT_UUID, manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestHomeInitialState:
    def test_new_home_under_construction_and_appointment_rejected(self, api):
        """PRD §3.1: "A new home starts in `UNDER_CONSTRUCTION` with
        `open_before_closing_count` and `open_after_closing_count` at zero."
        PRD §3.2: "The referenced home must be `PRE_CLOSE_READY` for a first
        orientation or `ORIENTED` for a re-orientation; any other home status
        rejects creation with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/home_initial_state_under_construction
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"], mark_ready=False)
        assert home["status"] == "UNDER_CONSTRUCTION", (
            f"new home must start UNDER_CONSTRUCTION, got {home['status']}"
        )
        resp = api.create_appointment(
            create_appointment_payload(
                home_id=home["id"], rep_id=rep["id"],
                scheduled_start="2026-08-25T14:00:00Z",
            ),
            make_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestAppointmentDefaults:
    def test_duration_defaults_from_community(self, api):
        """PRD §3.2: "a `CustomerCareRep` schedules the orientation by providing
        `home_id`, `rep_id`, `scheduled_start`, and an optional `duration_minutes`
        that defaults to the community's `appointment_duration_minutes` when
        omitted."
        PRD §3.1: "`appointment_duration_minutes` (default 120)"

        Design: Corner/entities/appointment_duration_defaults_from_community
        """
        community, buyer, rep = fx.setup_base()
        home = fx.setup_home(community["id"], buyer["id"])
        appt = fx.create_appointment(home["id"], rep["id"], "2026-08-25T14:00:00Z")
        assert appt["duration_minutes"] == 120, (
            f"duration must default to the community default 120, got {appt['duration_minutes']}"
        )
