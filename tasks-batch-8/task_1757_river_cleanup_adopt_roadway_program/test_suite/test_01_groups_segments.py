"""Group registration and segment mapping (PRD §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_adopter_group,
    assert_road_segment,
    create_group_payload,
    create_segment_payload,
    make_coordinator_headers,
    make_group_leader_headers,
    validate_error,
    validate_success,
)

COORD = make_coordinator_headers()


class TestGroupCreation:
    def test_group_creation_returns_201_with_server_fields(self, api):
        """PRD §3.1: "A `GroupLeader` registers the group by supplying its
        public `name`, an `org_type` of `CIVIC`, `BUSINESS`, `SCHOOL`, `FAITH`,
        or `OTHER`, a `contact_name`, and a `contact_email`."
        PRD §2.5: "At startup the logical clock reads exactly 2026-08-01T00:00:00Z."

        Design: Corner/entities/group_creation_returns_201_with_server_fields
        """
        resp = api.create_group(
            create_group_payload(), make_group_leader_headers("bootstrap-1")
        )
        data = validate_success(resp, 201)
        assert_adopter_group(data)
        assert data["version"] == 1
        assert data["created_at"] == "2026-08-01T00:00:00Z"
        assert data["org_type"] == "CIVIC"

    def test_group_creation_echoes_org_type_and_stamps_clock(self, api):
        """PRD §3.1: "A `GroupLeader` registers the group by supplying its
        public `name`, an `org_type` of `CIVIC`, `BUSINESS`, `SCHOOL`, `FAITH`,
        or `OTHER`, a `contact_name`, and a `contact_email`."
        PRD §2.5: "At startup the logical clock reads exactly 2026-08-01T00:00:00Z."

        Design: Corner/entities/group_creation_returns_201_with_server_fields
        """
        resp = api.create_group(
            create_group_payload(org_type="SCHOOL", name="Scout Troop 9"),
            make_group_leader_headers("bootstrap-2"),
        )
        data = validate_success(resp, 201)
        assert data["org_type"] == "SCHOOL"
        assert data["name"] == "Scout Troop 9"
        assert data["created_at"] == "2026-08-01T00:00:00Z"

    def test_group_missing_required_name_returns_invalid_request(self, api):
        """PRD §2.11 family 5: "Request shape — required fields present, types
        and enum values valid, ranges respected: ... (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/group_missing_required_name_returns_invalid_request
        """
        payload = {
            "org_type": "CIVIC",
            "contact_name": "Gina Lead",
            "contact_email": "gina@riverkeepers.org",
        }
        resp = api.create_group(payload, make_group_leader_headers("bootstrap-3"))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    @pytest.mark.parametrize("missing_field", ["name", "org_type", "contact_name", "contact_email"])
    def test_group_missing_each_required_field(self, api, missing_field):
        """PRD §2.11 family 5: "Request shape — required fields present, types
        and enum values valid, ranges respected: ... (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/group_missing_required_name_returns_invalid_request
        """
        payload = create_group_payload()
        payload.pop(missing_field)
        resp = api.create_group(payload, make_group_leader_headers("bootstrap-4"))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestSegmentMapping:
    def test_segment_mile_length_computed_from_markers(self, api):
        """PRD §2.8: "A road segment's `mile_length` is the difference between
        its end and start mile markers, rounded half-up to two decimal places."
        PRD §3.1: "an optional `water_adjacent` flag that defaults to false"
        PRD §3.1: "a new segment begins life `AVAILABLE`."

        Design: Corner/entities/segment_mile_length_computed_from_markers
        """
        resp = api.create_segment(
            create_segment_payload(
                route_name="Hill Rd",
                mile_marker_start=10.0,
                mile_marker_end=11.55,
                segment_type="ROADWAY",
            ),
            COORD,
        )
        data = validate_success(resp, 201)
        assert_road_segment(data)
        assert data["mile_length"] == pytest.approx(1.55, abs=1e-9)
        assert data["water_adjacent"] is False
        assert data["status"] == "AVAILABLE"

    def test_segment_water_adjacent_accepted_and_echoed(self, api):
        """PRD §3.1: "an optional `water_adjacent` flag that defaults to false
        and records whether the segment borders water."

        Design: Corner/entities/segment_mile_length_computed_from_markers
        """
        resp = api.create_segment(
            create_segment_payload(water_adjacent=True),
            COORD,
        )
        data = validate_success(resp, 201)
        assert data["water_adjacent"] is True

    def test_segment_invalid_marker_range_returns_invalid_request(self, api):
        """PRD §3.1: "a `mile_marker_start` and a `mile_marker_end` — the end
        marker must be strictly greater than the start marker"
        PRD §2.11 family 5: "**Request shape** — required fields present, types
        and enum values valid, ranges respected: `expected_volunteers` at least
        1; `mile_marker_end` strictly greater than `mile_marker_start`;
        `sign_text` between 1 and 60 characters; `dob` a date in the past; a
        `decision` value within the deciding endpoint's enumerated choices
        (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/segment_invalid_marker_range_returns_invalid_request
        """
        resp = api.create_segment(
            create_segment_payload(
                route_name="Bad Rd",
                mile_marker_start=6.0,
                mile_marker_end=4.0,
                segment_type="ROADWAY",
            ),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_segment_invalid_segment_type_returns_invalid_request(self, api):
        """PRD §2.11 family 5: "**Request shape** — required fields present,
        types and enum values valid, ranges respected: `expected_volunteers` at
        least 1; `mile_marker_end` strictly greater than `mile_marker_start`;
        `sign_text` between 1 and 60 characters; `dob` a date in the past; a
        `decision` value within the deciding endpoint's enumerated choices
        (`ERR_INVALID_REQUEST`)."
        PRD §3.1: "a `segment_type` of `ROADWAY` for roadside segments or
        `RIVERBANK` for river cleanup reaches"

        Design: Corner/entities/segment_invalid_marker_range_returns_invalid_request
        """
        resp = api.create_segment(
            create_segment_payload(segment_type="HIGHWAY"),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_segment_equal_markers_rejected(self, api):
        """PRD §3.1: "the end marker must be strictly greater than the start
        marker"

        Design: Corner/entities/segment_invalid_marker_range_returns_invalid_request
        """
        resp = api.create_segment(
            create_segment_payload(mile_marker_start=5.0, mile_marker_end=5.0),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
