"""Bootstrap and basic envelope coverage (corner index: entities section).

These tests verify foundational creation and read paths used by every other
test file.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_agreement_payload,
    create_network_payload,
    create_station_group_payload,
    create_station_payload,
    get_success_data,
    make_nar_headers,
    make_platform_admin_headers,
    setup_basic_scenario,
    setup_clock,
    validate_error,
    validate_success,
)
from test_helpers import api_client


class TestNetworkBootstrap:
    def test_network_creation_returns_normal_posture_and_zero_period(self, api):
        """PRD §3.1: "The network is born with `current_period_index` equal
        to 0, `current_utc` at the default clock, and `posture` equal to
        `NORMAL`."

        Design: Corner/entities/network_creation_returns_201_with_required_fields
        """
        headers = make_platform_admin_headers()
        resp = api.create_network(create_network_payload(), headers)
        data = validate_success(resp, expected_status=201)
        nid = data["id"]

        get_resp = api.get_network(nid, headers)
        fetched = validate_success(get_resp, expected_status=200)
        assert fetched["posture"] == "NORMAL", (
            f"Network posture on birth must be NORMAL, got {fetched['posture']!r}"
        )
        assert fetched["current_period_index"] == 0, (
            f"Network born at period 0, got {fetched['current_period_index']!r}"
        )
        assert fetched["version"] == 1, (
            f"Per PRD §2.4 every entity starts at version 1; got {fetched['version']!r}"
        )


class TestNotFound:
    def test_get_station_with_unknown_id_returns_not_found(self, api):
        """PRD §2.5: "A failure at any tier returns `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/station_get_not_found_returns_404
        """
        headers = make_platform_admin_headers()
        net = get_success_data(api.create_network(create_network_payload(), headers))
        resp = api.get_station(net["id"], NON_EXISTENT_UUID, headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestRequiredFields:
    def test_agreement_missing_reverse_comp_pct_rejected(self, api):
        """PRD §2.10: "Malformed payloads and missing required fields are
        rejected with `ERR_INVALID_REQUEST` (HTTP 400) before any of the
        above checks."

        Design: Corner/entities/agreement_missing_required_field_returns_invalid_request
        """
        setup_clock("2026-05-01T00:00:00Z")
        headers = make_platform_admin_headers()
        nar = make_nar_headers()
        net = get_success_data(api.create_network(create_network_payload(), headers))
        grp = get_success_data(api.create_station_group(create_station_group_payload(), headers))
        station = get_success_data(
            api.create_station(
                net["id"],
                create_station_payload(station_group_id=grp["id"]),
                nar,
            )
        )
        bad_payload = {
            "term_start_utc": "2026-01-01T00:00:00Z",
            "term_end_utc": "2027-01-01T00:00:00Z",
            # reverse_comp_pct omitted
            "retrans_share_pct": 0.60,
            "clearance_obligation_hours": 100,
        }
        resp = api.create_agreement(net["id"], station["id"], bad_payload, nar)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestStationComputedDefaults:
    def test_station_created_with_clearance_ok_posture_and_zero_minutes(self, api):
        """PRD §3.1: "The station is created with `posture` equal to
        `CLEARANCE_OK`, `monthly_outage_minutes_current_period` equal to 0,
        and `clearance_rate_current_period` null until a first clearance
        report is filed."

        Design: Corner/entities/station_posture_computed_field_initial_value
        """
        setup_clock("2026-05-01T00:00:00Z")
        headers = make_platform_admin_headers()
        nar = make_nar_headers()
        net = get_success_data(api.create_network(create_network_payload(), headers))
        grp = get_success_data(api.create_station_group(create_station_group_payload(), headers))
        resp = api.create_station(
            net["id"], create_station_payload(station_group_id=grp["id"]), nar
        )
        data = validate_success(resp, expected_status=201)
        assert data["posture"] == "CLEARANCE_OK", (
            f"New station posture must be CLEARANCE_OK; got {data['posture']!r}"
        )
        assert data["monthly_outage_minutes_current_period"] == 0, (
            f"New station outage minutes must be 0; got "
            f"{data['monthly_outage_minutes_current_period']!r}"
        )
