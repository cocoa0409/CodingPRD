"""Profile bootstrap and aircraft register — corner coverage."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_aircraft_payload,
    create_profile_payload,
    get_success_data,
    set_clock,
    setup_compliant_index_c_airport,
    setup_profile_only,
    validate_error,
    validate_paginated,
    validate_success,
)

AM = TEST_USERS["airport_manager_headers"]
AC = TEST_USERS["arff_chief_headers"]


class TestProfileBootstrap:
    def test_profile_create_initializes_computed_fields(self, api):
        """PRD §3.1: "The profile's initial `required_index_by_aircraft` is `A`
        because no aircraft are registered yet; both
        `supported_index_by_equipment` and `supported_index_by_staffing`
        evaluate to `NONE` until vehicles, readiness checks, and current
        firefighters exist; the resulting `effective_index` is therefore
        `NONE`, and `index_compliance_status` evaluates accordingly (since
        `NONE` is below `A`, the very first status is `NONCOMPLIANT` until the
        fleet and roster catch up)."

        Design: Corner/entities/ent_profile_create_computed_initial_and_singleton_rejected
        """
        set_clock("2026-05-01T00:00:00Z")
        resp = api.create_profile(
            create_profile_payload(airport_code="KDEMO", certificated_index="C"),
            AM,
        )
        data = validate_success(resp, expected_status=201)
        assert data["required_index_by_aircraft"] == "A"
        assert data["supported_index_by_equipment"] == "NONE"
        assert data["supported_index_by_staffing"] == "NONE"
        assert data["effective_index"] == "NONE"
        assert data["index_compliance_status"] == "NONCOMPLIANT"

    def test_profile_second_create_rejected_singleton(self, api):
        """PRD §2.6: "A second attempt to create the profile is rejected with
        `ERR_PROFILE_ALREADY_EXISTS` (HTTP 409)."

        Design: Corner/entities/ent_profile_create_computed_initial_and_singleton_rejected
        """
        setup_profile_only(airport_code="KDEMO", certificated_index="C")
        resp = api.create_profile(
            create_profile_payload(airport_code="KDUP", certificated_index="A"),
            AM,
        )
        validate_error(resp, ApiErrorId.ERR_PROFILE_ALREADY_EXISTS)


class TestAircraftBands:
    def test_aircraft_band_edges(self, api):
        """PRD §3.1: "`index_band` derives from `length_ft` with inclusive
        lower bounds and exclusive upper bounds: `A` when `length_ft` is below
        90 feet; `B` when `length_ft` is at least 90 and below 126; `C` when at
        least 126 and below 159; `D` when at least 159 and below 200; and `E`
        when at least 200 feet."

        Design: Corner/entities/ent_aircraft_band_edges_and_defaults
        """
        setup_profile_only(certificated_index="E")
        cases = [
            ("C172", 89.9, "A"),
            ("E190", 90.0, "B"),
            ("A321", 126.0, "C"),
            ("B767", 159.0, "D"),
            ("A380", 200.0, "E"),
        ]
        for model, length, expected in cases:
            resp = api.create_aircraft(
                create_aircraft_payload(
                    model_name=model, length_ft=length, avg_daily_departures=0,
                ),
                AM,
            )
            data = validate_success(resp, expected_status=201)
            assert data["index_band"] == expected, (
                f"length {length} expected band {expected}, "
                f"got {data['index_band']}"
            )

    def test_aircraft_in_scheduled_service_default_true(self, api):
        """PRD §3.1: "the `AirportManager` registers each aircraft type with
        `model_name`, `length_ft`, `avg_daily_departures`, and an optional
        `in_scheduled_service` flag that defaults to `true`."

        Design: Corner/entities/ent_aircraft_band_edges_and_defaults
        """
        setup_profile_only(certificated_index="E")
        # Omit in_scheduled_service
        resp = api.create_aircraft(
            {
                "model_name": "C172",
                "length_ft": 89.9,
                "avg_daily_departures": 0,
            },
            AM,
        )
        data = validate_success(resp, expected_status=201)
        assert data["in_scheduled_service"] is True


class TestAircraftNotFound:
    def test_get_aircraft_unknown_id_returns_404(self, api):
        """PRD §2.9: "The leftmost path `id` is resolved first; if it does not
        exist, the request is rejected with the corresponding
        `ERR_<RESOURCE>_NOT_FOUND` (HTTP 404) before any right-hand identifier
        is examined."

        Design: Corner/entities/ent_aircraft_not_found_returns_404
        """
        setup_profile_only()
        resp = api.get_aircraft(NON_EXISTENT_UUID, AM)
        validate_error(resp, ApiErrorId.ERR_AIRCRAFT_NOT_FOUND)


class TestRequiredIndexFiltering:
    def test_required_index_ignores_non_qualifying_larger_aircraft(self, api):
        """PRD §3.1: "`required_index_by_aircraft` aggregates across the
        entire aircraft register: consider only rows where
        `in_scheduled_service` is `true` and `avg_daily_departures` is at
        least `5.0`."

        Design: Corner/calculations/calc_required_index_ignores_non_qualifying_larger_aircraft
        """
        setup_profile_only(certificated_index="E")
        r1 = api.create_aircraft(
            create_aircraft_payload(
                model_name="A380", length_ft=238.6,
                avg_daily_departures=3.0, in_scheduled_service=True,
            ),
            AM,
        )
        a380 = validate_success(r1, expected_status=201)
        r2 = api.create_aircraft(
            create_aircraft_payload(
                model_name="B737-900", length_ft=138.2,
                avg_daily_departures=6.0, in_scheduled_service=True,
            ),
            AM,
        )
        b737 = validate_success(r2, expected_status=201)
        assert a380["qualifies_for_index"] is False
        assert b737["qualifies_for_index"] is True
        profile = get_success_data(api.get_profile(AM))
        assert profile["required_index_by_aircraft"] == "C"


class TestAircraftPagination:
    def test_aircraft_pagination_defaults_and_limit_offset(self, api):
        """PRD §2.3: "List endpoints accept two query parameters: `limit`
        (default 10, minimum 1, maximum 100) and `offset` (default 0). List
        responses populate the `meta` envelope with `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/endpoints/ep_pagination_defaults_and_limit_offset
        """
        setup_profile_only(certificated_index="E")
        for model, length, deps in [
            ("C172", 27.0, 2.0),
            ("E190", 118.9, 4.0),
            ("B737-900", 138.2, 6.0),
        ]:
            api.create_aircraft(
                create_aircraft_payload(
                    model_name=model, length_ft=length,
                    avg_daily_departures=deps,
                ),
                AM,
            )
        # Default list: limit 10
        data, meta = validate_paginated(api.list_aircraft(AM))
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(data) == 3
        # limit=2
        data, meta = validate_paginated(api.list_aircraft(AM, params={"limit": 2}))
        assert len(data) == 2
        assert meta["has_more"] is True
        assert meta["total_count"] == 3
        # limit=2, offset=2
        data, meta = validate_paginated(
            api.list_aircraft(AM, params={"limit": 2, "offset": 2})
        )
        assert len(data) == 1
        assert meta["has_more"] is False
