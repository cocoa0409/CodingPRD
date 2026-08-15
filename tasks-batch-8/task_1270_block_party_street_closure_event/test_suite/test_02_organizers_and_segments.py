"""Organizer registration, standing demotion, and street segment registry (PRD §3.1)."""
import pytest

from test_helpers import (
    ADMIN,
    api_client,
    assert_organizer,
    assert_street_segment,
    create_organizer_payload,
    create_organizer_record,
    create_segment_record,
    create_street_segment_payload,
    make_organizer_headers,
    validate_error,
    validate_success,
)


class TestOrganizerRegistration:
    def test_organizer_create_ignores_client_system_fields(self, api, anonymous_headers):
        """PRD §3.1: "The new record starts with `standing` set to `GOOD` and a
        `forfeiture_count` of zero."

        Design: Corner/entities/organizer_create_extra_system_fields_input_ignored
        """
        payload = create_organizer_payload(
            full_name="Sara Il", standing="SUSPENDED", forfeiture_count=9
        )
        organizer = validate_success(api.create_organizer(payload, anonymous_headers), 201)
        assert_organizer(organizer)
        assert organizer["standing"] == "GOOD", "client-supplied standing must be ignored"
        assert organizer["forfeiture_count"] == 0, "client-supplied forfeiture_count must be ignored"


class TestStreetSegmentRegistry:
    def test_segment_create_missing_household_count_400(self, api, city_admin_headers):
        """PRD §2.6: "a missing required field, an unrecognized enum value, or a numeric
        constraint violation (for example a non-positive `expected_attendance`, or a
        `returned_units` outside its allowed range) is rejected with `ERR_INVALID_REQUEST`
        (HTTP 400)."
        PRD §3.1: "a `CityAdmin` registers each closable **StreetSegment** with a human
        label `name` (for example, "Maple Ave 100-block"), a `jurisdiction` of `CITY`,
        `COUNTY`, or `STATE_ROUTE`, a `segment_kind` of `RESIDENTIAL` or `MIXED_USE`, the
        `household_count` of homes fronting the segment (zero or more)".

        Design: Corner/entities/street_segment_missing_required_household_count_returns_400
        """
        payload = create_street_segment_payload()
        del payload["household_count"]
        res = api.create_street_segment(payload, city_admin_headers)
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_segment_optional_fields_default(self, api, city_admin_headers):
        """PRD §3.1: "an optional `business_count` of business frontages (defaulting to 0,
        also zero or more), an optional `intersects_arterial` flag (defaulting to false)
        recording whether the closure touches an arterial intersection".

        Design: Corner/entities/segment_defaults_applied
        """
        payload = create_street_segment_payload(
            name="Elm Def", household_count=5, length_m=48
        )
        assert "business_count" not in payload
        assert "intersects_arterial" not in payload
        segment = validate_success(api.create_street_segment(payload, city_admin_headers), 201)
        assert_street_segment(segment)
        assert segment["business_count"] == 0
        assert segment["intersects_arterial"] is False


class TestOrganizerStanding:
    def test_suspended_organizer_cannot_create_petition(self, api, city_admin_headers):
        """PRD §3.1: "each deposit forfeiture increments `forfeiture_count` by one, the first
        forfeiture demotes `standing` from `GOOD` to `FLAGGED`, and the second demotes it
        from `FLAGGED` to `SUSPENDED`, at which point the organizer can no longer open
        petitions or applications — attempts are rejected with `ERR_ORGANIZER_SUSPENDED`."
        PRD §3.1: "For test-driving purposes, a `CityAdmin` can apply exactly one such
        forfeiture demotion directly to an organizer identified by `organizer_id`, without
        running a full event lifecycle."

        Design: Corner/errors/organizer_suspended_cannot_create_returns_403
        """
        organizer = create_organizer_record()
        first = validate_success(
            api.inject_organizer_forfeiture({"organizer_id": organizer["id"]}, city_admin_headers), 200
        )
        assert first["standing"] == "FLAGGED"
        assert first["forfeiture_count"] == 1
        second = validate_success(
            api.inject_organizer_forfeiture({"organizer_id": organizer["id"]}, city_admin_headers), 200
        )
        assert second["standing"] == "SUSPENDED"
        assert second["forfeiture_count"] == 2

        segment = create_segment_record()
        res = api.create_petition({"segment_id": segment["id"]}, make_organizer_headers(organizer["id"]))
        validate_error(res, "ERR_ORGANIZER_SUSPENDED")
