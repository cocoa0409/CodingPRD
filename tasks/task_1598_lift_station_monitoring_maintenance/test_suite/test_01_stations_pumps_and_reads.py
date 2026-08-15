"""Stations, pumps, and telemetry: creation, defaults, retrieval, listing,
firm-capacity calculation, runtime accumulation, and read-after-write
consistency."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_pump,
    assert_runtime_reading,
    assert_station,
    create_alarm_ticket_payload,
    create_pump_payload,
    create_station_payload,
    add_pump,
    add_reading,
    create_station,
    get_pump,
    get_station,
    raise_ticket,
    reset_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStationCreation:
    def test_create_station_with_required_fields_returns_201(self, api, utility_admin_headers):
        """PRD §3.1: "A `UtilityAdmin` onboards a station by supplying its
        regulatory `station_code`, the owning `service_zone`, the rated
        `design_capacity_gpm`, the number of installed `pump_count` slots,
        whether it `has_backup_generator`, and the physical `wet_well_volume_gal`."
        PRD §3.1: "A newly created station begins life in posture `NORMAL`, with
        `firm_capacity_available_gpm` computed from its pumps and
        `last_sso_occurred_at` null until an overflow occurs."
        PRD §2.4: "every resource also carries `created_at` and `updated_at` as
        ISO 8601 UTC timestamps with three fractional digits, plus a `version`
        integer that starts at 1 on creation and increments by exactly 1 on
        every mutation of that resource"

        Design: Corner/entities/create_station_with_required_fields_returns_201
        """
        reset_clock()
        res = api.create_station(
            create_station_payload(
                station_code="LS-0001", design_capacity_gpm=500, pump_count=2,
                has_backup_generator=True, wet_well_volume_gal=5000,
            ),
            utility_admin_headers,
        )
        station = validate_success(res, 201)
        assert_station(station)
        assert station["station_code"] == "LS-0001"
        assert station["operational_posture"] == "NORMAL"
        assert station["version"] == 1

    def test_get_station_returns_stored_data(self, api, utility_admin_headers,
                                             operations_supervisor_headers):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.1: "A `UtilityAdmin` onboards a station by supplying its
        regulatory `station_code`, the owning `service_zone`, the rated
        `design_capacity_gpm`, the number of installed `pump_count` slots,
        whether it `has_backup_generator`, and the physical `wet_well_volume_gal`."

        Design: Corner/entities/get_station_returns_stored_data
        """
        reset_clock()
        station = create_station(
            station_code="LS-0002", service_zone="Z9", design_capacity_gpm=750,
            pump_count=3, wet_well_volume_gal=8000,
        )
        res = api.get_station(station["id"], operations_supervisor_headers)
        fetched = validate_success(res, 200)
        assert_station(fetched)
        assert fetched["station_code"] == "LS-0002"
        assert fetched["service_zone"] == "Z9"
        assert fetched["design_capacity_gpm"] == 750

    def test_list_stations_pagination(self, api, utility_admin_headers):
        """PRD §2.3: "List responses include the pagination fields `limit`,
        `offset`, `total_count`, and `has_more` inside the `meta` object, where
        `total_count` reports the full size of the filtered result set and
        `has_more` indicates whether additional pages exist beyond the returned
        window."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        Design: Corner/entities/list_stations_pagination
        """
        reset_clock()
        for code in ("LS-0010", "LS-0011", "LS-0012"):
            create_station(station_code=code)
        res = api.list_stations(utility_admin_headers, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(res)
        assert len(data) == 2, f"expected page of 2, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert isinstance(meta.get("api_request_id"), str)
        assert meta["api_request_id"].startswith("req_")

    def test_get_station_nonexistent_returns_404(self, api, utility_admin_headers):
        """PRD §2.8: "path identifiers are resolved left to right, and the first
        identifier that does not resolve to an existing row produces
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_station_nonexistent_returns_404
        """
        reset_clock()
        res = api.get_station(NON_EXISTENT_UUID, utility_admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)

    def test_create_station_missing_required_returns_invalid_request(
        self, api, utility_admin_headers
    ):
        """PRD §2.8: "then temporal rules (reading order, test duration, grease
        depth, report deadline); then referential rules (open SSO, permit
        required, permit expired, budget); then fiscal rules (settlement period,
        plan lock); then dispatch eligibility; and finally generic shape
        validation (`ERR_INVALID_REQUEST`) for required-field presence, enum
        membership, and simple numeric ranges."
        PRD §3.1: "The `design_capacity_gpm` must be a positive integer no
        smaller than 50, `pump_count` must be an integer between 2 and 8
        inclusive, and `wet_well_volume_gal` must be a positive integer — shape
        violations of these kinds surface as `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/create_station_missing_required_returns_invalid_request
        """
        reset_clock()
        payload = {
            "station_code": "LS-0020",
            "service_zone": "Z1",
            "pump_count": 2,
            "has_backup_generator": True,
            "wet_well_volume_gal": 5000,
        }
        res = api.create_station(payload, utility_admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_computed_posture_is_server_computed_on_create(self, api, utility_admin_headers):
        """PRD §3.1: "A newly created station begins life in posture `NORMAL`,
        with `firm_capacity_available_gpm` computed from its pumps and
        `last_sso_occurred_at` null until an overflow occurs."
        PRD §2.7: "Each lift station continuously derives an
        `operational_posture` of `NORMAL`, `DEGRADED`, `EMERGENCY`, or `FROZEN`."

        Design: Corner/entities/computed_fields_input_ignored_on_station
        """
        reset_clock()
        res = api.create_station(
            create_station_payload(
                station_code="LS-0040", design_capacity_gpm=500, pump_count=2,
                wet_well_volume_gal=5000,
            ),
            utility_admin_headers,
        )
        station = validate_success(res, 201)
        assert station["operational_posture"] == "NORMAL", (
            "posture is server-derived, not client-supplied"
        )
        assert station["firm_capacity_available_gpm"] == 0, (
            "with no pumps, firm capacity is zero"
        )
        assert station["last_sso_occurred_at"] is None


class TestDefaultsAndTypes:
    def test_alarm_ticket_is_sso_related_default_false(self, api, scada_webhook_headers):
        """PRD §3.3: "An alarm ticket is born when SCADA or a human raises one
        against a station, supplying `alarm_class` (`CRITICAL`, `MAJOR`,
        `MINOR`, or `INFO`), the SCADA-originated `alarm_code` (such as
        `HI_LEVEL`, `P1_FAIL`, `GEN_FAIL`, or `COMM_LOSS`), the `raised_at`
        instant, and an optional `is_sso_related` flag that defaults to false."

        Design: Corner/entities/alarm_ticket_is_sso_related_default_false
        """
        reset_clock()
        station = create_station(station_code="LS-0030")
        payload = {
            "alarm_class": "INFO",
            "alarm_code": "TEST",
            "raised_at": "2026-08-01T00:00:00Z",
        }
        res = api.create_alarm_ticket(station["id"], payload, scada_webhook_headers)
        ticket = validate_success(res, 201)
        assert ticket["is_sso_related"] is False

    def test_pump_status_default_in_service(self, api, utility_admin_headers):
        """PRD §3.2: "Pumps are registered against a station by a
        `MaintenancePlanner` or `UtilityAdmin`, naming the `station_id`, a
        1-based physical `position_index`, and a nameplate `rated_gpm`; an
        optional `status` may be supplied but defaults to `IN_SERVICE`."

        Design: Corner/entities/pump_status_default_in_service
        """
        reset_clock()
        station = create_station(station_code="LS-0031")
        res = api.create_pump(
            {"station_id": station["id"], "position_index": 1, "rated_gpm": 150},
            utility_admin_headers,
        )
        pump = validate_success(res, 201)
        assert_pump(pump)
        assert pump["status"] == "IN_SERVICE"

    def test_invalid_enum_value_returns_invalid_request(self, api, utility_admin_headers):
        """PRD §2.8: "and finally generic shape validation
        (`ERR_INVALID_REQUEST`) for required-field presence, enum membership,
        and simple numeric ranges."
        PRD §3.2: "Each pump tracks `cumulative_runtime_hours` (lifetime run
        time), `runtime_since_rebuild_hours` (run time since the most recent
        completed rebuild), `last_alternation_at` (when it last became lead),
        and `rebuild_count` (completed rebuilds, starting at 0)."

        Design: Corner/entities/invalid_enum_value_returns_invalid_request
        """
        reset_clock()
        station = create_station(station_code="LS-0041")
        res = api.create_pump(
            {"station_id": station["id"], "position_index": 1, "rated_gpm": 100,
             "status": "BOGUS"},
            utility_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_runtime_reading_immutable_no_update_endpoint(self, api, utility_admin_headers):
        """PRD §2.4: "The exception is the runtime-reading feed: because
        readings are an append-only telemetry stream, a runtime reading carries
        only `id` and `created_at`; `updated_at` and `version` are absent from
        that resource entirely and must not appear in its serialized form."
        PRD §3.2: "Readings can be listed with optional `since` and `until`
        bounds plus standard pagination."

        Design: Corner/entities/runtime_reading_immutable_no_update_endpoint
        """
        reset_clock()
        station = create_station(station_code="LS-0042")
        pump = add_pump(station["id"], position_index=1, rated_gpm=100)
        reading = add_reading(
            pump["id"], "2026-08-01T00:00:00Z", 1.5, starts_count=2,
        )
        assert_runtime_reading(reading)
        res = api.list_runtime_readings(pump["id"], utility_admin_headers)
        data, meta = validate_paginated(res)
        assert len(data) == 1
        assert data[0]["id"] == reading["id"]
        assert_runtime_reading(data[0])


class TestFirmCapacity:
    def test_firm_capacity_n_minus_1_computed_correctly(self, api, utility_admin_headers):
        """PRD §3.2: "A station's firm capacity follows the N-1 criterion:
        `firm_capacity_available_gpm` is the sum of `rated_gpm` across the
        station's pumps whose status is `IN_SERVICE`, minus the largest single
        `rated_gpm` among those pumps."

        Design: Corner/calculations/firm_capacity_n_minus_1_computed_correctly
        """
        reset_clock()
        station = create_station(
            station_code="LS-0200", design_capacity_gpm=500, pump_count=3,
        )
        add_pump(station["id"], 1, 100)
        add_pump(station["id"], 2, 200)
        add_pump(station["id"], 3, 300)
        res = api.get_station(station["id"], utility_admin_headers)
        station_after = validate_success(res, 200)
        assert_station(station_after)
        assert station_after["firm_capacity_available_gpm"] == 300, (
            "sum 600 minus largest 300"
        )

    def test_firm_capacity_excludes_non_in_service(self, api, utility_admin_headers):
        """PRD §3.2: "Pumps in `STANDBY`, `OUT_OF_SERVICE`, or `REBUILD`
        contribute nothing."
        PRD §3.2: "If no pump is `IN_SERVICE`, firm capacity is zero."

        Design: Corner/calculations/firm_capacity_excludes_non_in_service
        """
        reset_clock()
        station = create_station(
            station_code="LS-0201", design_capacity_gpm=300, pump_count=4,
        )
        add_pump(station["id"], 1, 200, status="IN_SERVICE")
        add_pump(station["id"], 2, 200, status="IN_SERVICE")
        add_pump(station["id"], 3, 200, status="STANDBY")
        add_pump(station["id"], 4, 200, status="OUT_OF_SERVICE")
        station_after = get_station(station["id"])
        assert station_after["firm_capacity_available_gpm"] == 200, (
            "only the two IN_SERVICE pumps count: 400 - 200"
        )

    def test_runtime_reading_accumulates(self, api, utility_admin_headers):
        """PRD §3.2: "Each accepted reading adds its `run_hours_delta` to both
        `cumulative_runtime_hours` and `runtime_since_rebuild_hours`; the latter
        resets to 0 only when a pump returns from rebuild."

        Design: Corner/calculations/runtime_reading_accumulates
        """
        reset_clock()
        station = create_station(station_code="LS-0205")
        pump = add_pump(station["id"], 1, 100)
        add_reading(pump["id"], "2026-08-01T01:00:00Z", 2.5, starts_count=3)
        res = api.create_runtime_reading(
            pump["id"],
            {"recorded_at": "2026-08-01T02:00:00Z", "run_hours_delta": 1.5,
             "starts_count": 2, "source": "SCADA"},
            utility_admin_headers,
        )
        validate_success(res, 201)
        pump_after = get_pump(pump["id"])
        assert pump_after["cumulative_runtime_hours"] == pytest.approx(4.0)
        assert pump_after["runtime_since_rebuild_hours"] == pytest.approx(4.0)


class TestStationComputedReads:
    def test_get_station_summary_returns_derived(self, api, utility_admin_headers):
        """PRD §3.11: "the platform exposes a computed per-station summary
        returning the station's `station_id`, its current `operational_posture`,
        the live `firm_capacity_available_gpm`, the count of open alarm tickets
        as `open_alarm_count`, the count of overdue cleanings as
        `overdue_cleaning_count`, the count of overdue generator tests as
        `overdue_generator_test_count`, the current
        `grease_accumulation_rate_inches_per_day`, the projected
        `next_cleaning_due_at`, and the station's `last_sso_occurred_at`."
        PRD §2.7: "Otherwise, if the station's available firm capacity has
        fallen below its design capacity, or any pump at the station is in
        `REBUILD`, or any generator test for the station is in `SCHEDULED`,
        `RUNNING`, or `FAILED` with its `scheduled_for` already in the past, the
        posture is `DEGRADED`."

        Design: Corner/endpoints/get_station_summary_returns_derived
        """
        reset_clock()
        station = create_station(
            station_code="LS-0500", design_capacity_gpm=300, pump_count=2,
        )
        add_pump(station["id"], 1, 150)
        add_pump(station["id"], 2, 150)
        res = api.get_station_summary(station["id"], utility_admin_headers)
        summary = validate_success(res, 200)
        assert summary["firm_capacity_available_gpm"] == 150, "sum 300 - largest 150"
        assert summary["operational_posture"] == "DEGRADED", "firm 150 < design 300"
        assert summary["station_id"] == station["id"]

    def test_filtered_list_pumps_by_station(self, api, utility_admin_headers):
        """PRD §4: "List Pumps; filterable by `station_id` and `status`."
        PRD §3.2: "Pumps are registered against a station by a
        `MaintenancePlanner` or `UtilityAdmin`, naming the `station_id`, a
        1-based physical `position_index`, and a nameplate `rated_gpm`"

        Design: Corner/endpoints/filtered_list_pumps_by_station
        """
        reset_clock()
        s1 = create_station(station_code="LS-0501")
        s2 = create_station(station_code="LS-0502")
        p1 = add_pump(s1["id"], 1, 100)
        p2 = add_pump(s2["id"], 1, 100)
        res = api.list_pumps(utility_admin_headers, params={"station_id": s1["id"]})
        data, meta = validate_paginated(res)
        ids = [row["id"] for row in data]
        assert p1["id"] in ids
        assert p2["id"] not in ids

    def test_sub_resource_station_pumps(self, api, utility_admin_headers):
        """PRD §4: "List Pumps for a station."
        PRD §2.3: "List endpoints accept two query parameters, `limit` and
        `offset`."

        Design: Corner/endpoints/sub_resource_station_pumps
        """
        reset_clock()
        station = create_station(station_code="LS-0503")
        p1 = add_pump(station["id"], 1, 100)
        p2 = add_pump(station["id"], 2, 100)
        res = api.list_station_pumps(station["id"], utility_admin_headers)
        data, meta = validate_paginated(res)
        ids = sorted(row["id"] for row in data)
        assert ids == sorted([p1["id"], p2["id"]]), "sub-resource returns both pumps"


class TestImmediateConsistency:
    def test_response_reflects_writes_immediately(self, api, utility_admin_headers,
                                                  operations_supervisor_headers):
        """PRD §3.4: "Moving a pump between `IN_SERVICE` and `STANDBY`, and
        returning a pump from `OUT_OF_SERVICE` to service, are
        `OperationsSupervisor` actions refused only at a frozen station."
        PRD §2.7: "When the station is not frozen, posture is recomputed on
        every state change of any child pump, alarm ticket, SSO event,
        confined-space permit, or generator test attached to the station."

        Design: Corner/consistency_model/response_reflects_writes_immediately
        """
        reset_clock()
        station = create_station(
            station_code="LS-0800", design_capacity_gpm=300, pump_count=2,
        )
        pump = add_pump(station["id"], 1, 100)
        add_pump(station["id"], 2, 100)
        res = api.standby_pump(pump["id"], operations_supervisor_headers)
        validate_success(res, 200)
        after = get_pump(pump["id"])
        assert after["status"] == "STANDBY", "write is visible on the very next read"

    def test_station_posture_reflects_pump_change_immediately(
        self, api, utility_admin_headers, operations_supervisor_headers
    ):
        """PRD §3.2: "This figure is recomputed on every pump status mutation,
        pump creation, and nameplate edit, and each recomputation in turn
        triggers a station-posture recompute — the compare of available firm
        capacity against `design_capacity_gpm` is one of the three drivers into
        `DEGRADED`."
        PRD §2.7: "Otherwise, if the station's available firm capacity has
        fallen below its design capacity, or any pump at the station is in
        `REBUILD`, or any generator test for the station is in `SCHEDULED`,
        `RUNNING`, or `FAILED` with its `scheduled_for` already in the past, the
        posture is `DEGRADED`."

        Design: Corner/consistency_model/station_posture_reflects_pump_change_immediately
        """
        reset_clock()
        station = create_station(
            station_code="LS-0801", design_capacity_gpm=400, pump_count=3,
        )
        p1 = add_pump(station["id"], 1, 200)
        add_pump(station["id"], 2, 200)
        add_pump(station["id"], 3, 200)
        res = api.mark_pump_out_of_service(p1["id"], operations_supervisor_headers)
        validate_success(res, 200)
        after = get_station(station["id"])
        assert after["firm_capacity_available_gpm"] == 200, "400 - largest 200"
        assert after["operational_posture"] == "DEGRADED", (
            "firm 200 below design 400 -> DEGRADED in the same request"
        )
