"""Station onboarding, lifecycle, posture readback, and visibility (PRD §2.4,
§2.7, §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_compressor,
    add_dispenser,
    assert_station,
    create_station,
    get_station,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStationCreateDefaults:
    def test_station_create_applies_initial_state(self, api, network_operator_headers):
        """PRD §3.1: "The station is born in SETUP status with `uptime_posture`
        OUTAGE and `version` 1, and it cannot fuel anyone until it is equipped
        and activated."
        PRD §2.5: "At startup the logical time is exactly 2026-08-01T00:00:00Z."

        Design: Corner/entities/station_create_applies_defaults
        """
        resp = api.create_station(
            {
                "station_name": "Tango",
                "station_code": "ST-TANGO",
                "access_mode": "DUAL",
                "backup_capacity_gge": 5000,
            },
            network_operator_headers,
        )
        data = validate_success(resp, 201)
        assert_station(data)
        assert data["status"] == "SETUP"
        assert data["uptime_posture"] == "OUTAGE", (
            "zero compressors / zero dispensers -> OUTAGE per PRD §2.7"
        )
        assert data["version"] == 1
        assert is_iso8601_timestamp(data["created_at"])
        assert data["created_at"].startswith("2026-08-01T00:00:00"), (
            f"created_at must equal the startup logical clock, got {data['created_at']}"
        )


class TestStationCreateValidation:
    def test_station_create_missing_required_field_returns_invalid_request(
        self, api, network_operator_headers
    ):
        """PRD §2.8: "Required fields must be present, enum values must be
        valid, numeric constraints must be honored ... Violations are
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/station_create_missing_required_field_returns_invalid_request
        """
        resp = api.create_station(
            {"station_name": "NoCode", "access_mode": "DUAL", "backup_capacity_gge": 5000},
            network_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_station_create_invalid_enum_rejected(self, api, network_operator_headers):
        """PRD §2.8: "Required fields must be present, enum values must be
        valid, numeric constraints must be honored ... Violations are
        `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "an `access_mode` of PUBLIC, PRIVATE, or DUAL declaring which
        session access types the station serves"

        Design: Corner/entities/station_create_invalid_enum_rejected
        """
        resp = api.create_station(
            {
                "station_name": "BadEnum",
                "station_code": "ST-BAD",
                "access_mode": "MIXED",
                "backup_capacity_gge": 5000,
            },
            network_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestStationListPagination:
    def test_station_list_pagination_envelope(self, api, network_operator_headers):
        """PRD §2.3: "`limit` controls page size: it defaults to 10, with a
        minimum of 1 and a maximum of 100. `offset` controls how many records
        to skip and defaults to 0. List responses carry the pagination fields
        `limit`, `offset`, `total_count`, and `has_more` in the `meta` object."

        Design: Corner/entities/station_list_pagination_envelope
        """
        for i in range(1, 4):
            create_station(
                station_name=f"P{i}",
                station_code=f"ST-PG{i}",
                access_mode="PUBLIC",
                backup_capacity_gge=1000,
            )
        page1, meta1 = validate_paginated(
            api.list_stations(network_operator_headers, params={"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_stations(network_operator_headers, params={"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestImmediateVisibility:
    def test_immediate_visibility_after_create(self, api, station_manager_headers):
        """PRD §2.4: "Consistency is immediate: every mutation is fully
        reflected in the response of the request that caused it."

        Design: Corner/consistency_model/immediate_visibility_after_create
        """
        station = create_station(station_name="ImmV", station_code="ST-IMMV")
        got = validate_success(api.get_station(station["id"], station_manager_headers), 200)
        assert got["status"] == "SETUP"
        rows, meta = validate_paginated(api.list_stations(station_manager_headers))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == station["id"]


class TestStationActivation:
    def test_station_activate_unequipped_rejected(self, api, network_operator_headers):
        """PRD §3.1: "The station must still be in SETUP, else
        `ERR_STATION_NOT_IN_SETUP` (HTTP 409), and it must have at least one
        compressor and at least one dispenser registered, else
        `ERR_STATION_NOT_EQUIPPED` (HTTP 409)."

        Design: Corner/validations/station_activate_unequipped_rejected
        """
        station = create_station(station_name="Empty", station_code="ST-EMPTY")
        resp = api.activate_station(station["id"], network_operator_headers)
        validate_error(resp, ApiErrorId.ERR_STATION_NOT_EQUIPPED, 409)
        assert get_station(station["id"])["status"] == "SETUP"

    def test_station_activate_twice_rejected(self, api, network_operator_headers):
        """PRD §3.1: "The station must still be in SETUP, else
        `ERR_STATION_NOT_IN_SETUP` (HTTP 409), and it must have at least one
        compressor and at least one dispenser registered, else
        `ERR_STATION_NOT_EQUIPPED` (HTTP 409)."

        Design: Corner/validations/station_activate_twice_rejected
        """
        station = create_station(station_name="TwiceA", station_code="ST-TWICEA")
        add_compressor(station["id"])
        add_dispenser(station["id"])
        validate_success(api.activate_station(station["id"], network_operator_headers), 200)
        resp = api.activate_station(station["id"], network_operator_headers)
        validate_error(resp, ApiErrorId.ERR_STATION_NOT_IN_SETUP, 409)

    def test_station_resume_when_not_suspended_rejected(self, api, network_operator_headers):
        """PRD §3.1: "Resumption returns a SUSPENDED station to ACTIVE; it
        requires the station to be SUSPENDED, else `ERR_STATION_NOT_SUSPENDED`
        (HTTP 409), and it is refused while any safety inspection at the
        station is OVERDUE, surfacing `ERR_OVERDUE_INSPECTION` (HTTP 409)."

        Design: Corner/validations/station_resume_when_not_suspended_rejected
        """
        station = create_station(station_name="ResA", station_code="ST-RESA")
        add_compressor(station["id"])
        add_dispenser(station["id"])
        validate_success(api.activate_station(station["id"], network_operator_headers), 200)
        resp = api.resume_station(station["id"], network_operator_headers)
        validate_error(resp, ApiErrorId.ERR_STATION_NOT_SUSPENDED, 409)


class TestPostureReadback:
    def test_posture_computed_readback_on_condition_change(
        self, api, station_manager_headers, network_operator_headers
    ):
        """PRD §2.7: "Count the station's compressors whose condition is ONLINE
        or DEGRADED, and count its dispensers whose status is IN_SERVICE. If
        either count is zero, the posture is OUTAGE."
        PRD §2.7: "Otherwise, if any compressor is DEGRADED or any dispenser is
        on CALIBRATION_HOLD, the posture is DEGRADED."

        Design: Corner/entities/posture_computed_readback_on_condition_change
        """
        station = create_station(station_name="Post", station_code="ST-POST")
        compressor = add_compressor(station["id"])
        add_dispenser(station["id"])
        activated = validate_success(
            api.activate_station(station["id"], network_operator_headers), 200
        )
        assert activated["uptime_posture"] == "OPERATIONAL"
        validate_success(
            api.report_compressor_condition(
                compressor["id"], {"condition": "DEGRADED"}, station_manager_headers
            ),
            200,
        )
        after = validate_success(api.get_station(station["id"], station_manager_headers), 200)
        assert after["uptime_posture"] == "DEGRADED", (
            "one DEGRADED compressor present, none offline -> DEGRADED"
        )
