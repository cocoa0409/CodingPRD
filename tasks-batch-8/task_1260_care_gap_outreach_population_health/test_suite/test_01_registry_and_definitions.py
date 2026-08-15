"""Registry, measure, cohort, and member definition claims (PRD §2.3, §2.8, §3.1)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, NON_EXISTENT_UUID, ApiErrorId,
    assert_registry, assert_measure,
    create_registry_payload, create_measure_payload, create_member_payload,
    make_admin_headers,
)


class TestRegistryCreation:
    def test_registry_creation_returns_default_fields(self, api):
        """PRD §3.1: "A new registry is immediately `ACTIVE` and its logical clock
        starts at the instant described in §2.5."
        PRD §2.5: "When a registry is created, its clock initializes to
        `2026-05-01T00:00:00Z`, and from then on time only moves forward through
        an administrator-only clock-advance capability"
        PRD §4: "Creating a new resource returns HTTP 201 with the created resource
        in `data`".

        Design: Corner/entities/registry_creation_returns_default_fields
        """
        resp = api.create_registry(create_registry_payload(name="R", program_year=2026),
                                   make_admin_headers())
        data = validate_success(resp, 201)
        assert_registry(data)
        assert data["status"] == "ACTIVE", f"Expected ACTIVE registry, got {data['status']}"
        assert data["id"] is not None
        # clock default instant (rendering may include fractional digits)
        from test_helpers import assert_timestamp_instant_equal
        assert_timestamp_instant_equal(data["current_business_date"], "2026-05-01T00:00:00Z",
                                       label="current_business_date")

    def test_registry_get_returns_stored_data(self, api):
        """PRD §3.1: "A `ProgramAdministrator` begins by creating a registry with a
        display `name`, an optional `description`, and a `program_year` identifying
        the measurement year; the program year is immutable once the registry exists."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource
        will return the created or updated resource object in the data field."

        Design: Corner/entities/registry_get_returns_stored_data
        """
        created = get_success_data(api.create_registry(
            create_registry_payload(name="RX", program_year=2026), make_admin_headers()))
        resp = api.get_registry(created["id"], make_admin_headers())
        data = validate_success(resp, 200)
        assert data["name"] == "RX", f"Expected name RX, got {data['name']}"
        assert data["program_year"] == 2026, (
            f"Expected program_year 2026, got {data['program_year']}")

    def test_registry_list_paginated(self, api):
        """PRD §2.3: "List endpoints accept two query parameters, `limit` and `offset`.
        The `limit` defaults to 10, must be at least 1, and may not exceed 100. The
        `offset` defaults to 0. List responses are sorted by `created_at` ascending,
        and the `meta` object of a list response carries the pagination fields
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/registry_list_paginated
        """
        get_success_data(api.create_registry(create_registry_payload(name="RA"),
                                             make_admin_headers()))
        get_success_data(api.create_registry(create_registry_payload(name="RB"),
                                             make_admin_headers()))
        resp = api.list_registries(make_admin_headers(), params={"limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 1, f"Expected 1 row under limit=1, got {len(data)}"
        assert meta["total_count"] == 2, f"Expected total_count 2, got {meta['total_count']}"
        assert meta["has_more"] is True, "Expected has_more true with 2 rows and limit 1"

    def test_registry_get_nonexistent_returns_not_found(self, api):
        """PRD §2.8: "then existence of every resource identifier in the path,
        evaluated left to right (failure yields `ERR_NOT_FOUND`, HTTP 404)".

        Design: Corner/entities/registry_get_nonexistent_returns_not_found
        """
        resp = api.get_registry(NON_EXISTENT_UUID, make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestMeasureDefinition:
    def test_measure_missing_required_field_returns_invalid_request(self, api):
        """PRD §3.1: "Each measure carries a `measure_code` unique within its registry
        (for example, a colorectal screening code), a `measure_domain` of either
        `SCREENING` or `MED_ADHERENCE`, and a `lookback_days` value stating how many
        days of history satisfy the gap"
        PRD §2.8: "Malformed bodies, missing required fields, and type mismatches are
        rejected with `ERR_INVALID_REQUEST` (HTTP 400) as the request is parsed."

        Design: Corner/entities/measure_missing_required_field_returns_invalid_request
        """
        registry = get_success_data(api.create_registry(create_registry_payload(),
                                                        make_admin_headers()))
        payload = {"measure_code": "SCR", "measure_domain": "SCREENING"}  # no lookback_days
        resp = api.create_measure(registry["id"], payload, make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_measure_exclusion_window_default_applied(self, api):
        """PRD §3.1: "Two timing knobs have defaults: `exclusion_window_days`, the
        number of days an approved exclusion suppresses the gap from the reporting
        denominator, defaults to 90; and `reporting_lag_days`, the number of days
        after period end that must elapse before the final report variant may be
        published, defaults to 30."

        Design: Corner/entities/measure_exclusion_window_default_applied
        """
        registry = get_success_data(api.create_registry(create_registry_payload(),
                                                        make_admin_headers()))
        resp = api.create_measure(
            registry["id"],
            create_measure_payload(measure_code="SCR", measure_domain="SCREENING",
                                   lookback_days=365),
            make_admin_headers(),
        )
        data = validate_success(resp, 201)
        assert_measure(data)
        assert data["exclusion_window_days"] == 90, (
            f"Expected default exclusion_window_days 90, got {data['exclusion_window_days']}")
        assert data["reporting_lag_days"] == 30, (
            f"Expected default reporting_lag_days 30, got {data['reporting_lag_days']}")


class TestMemberRegistration:
    def test_member_enrollment_status_enum_enforced(self, api):
        """PRD §3.1: "Members are registered into a registry with a medical record
        number `mrn` that is unique within the registry, a `date_of_birth`, a
        `risk_tier` of `LOW`, `MEDIUM`, or `HIGH`"
        PRD §2.8: "Malformed bodies, missing required fields, and type mismatches are
        rejected with `ERR_INVALID_REQUEST` (HTTP 400) as the request is parsed."

        Design: Corner/entities/member_enrollment_status_enum_enforced
        """
        registry = get_success_data(api.create_registry(create_registry_payload(),
                                                        make_admin_headers()))
        payload = create_member_payload(mrn="M", risk_tier="ULTRA")
        resp = api.create_member(registry["id"], payload, make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
