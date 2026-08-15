"""Entity creation, defaults, computed-field initialization, and input validation."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_customer_site,
    create_site_payload,
    create_vessel_payload,
    make_plant_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSiteCreation:
    def test_site_creation_defaults_applied(self, api, service_manager_headers):
        """PRD §3.1: "The site optionally carries a `contract_discount_pct` (default 0,
        range 0–100) applied to estimates and invoices, a `capital_threshold_cents`
        (default 500000 integer cents — i.e. $5,000.00) above which quoted tickets
        route to the capital-project track, and a `credit_hold` boolean (default
        false) that, when true, blocks scheduling of new service. A newly created
        site has no vessels, so its `site_posture` is `NORMAL`."

        Design: Corner/entities/site_creation_defaults_applied
        """
        res = api.create_site(
            create_site_payload(name="Defaults Site", state_code="IA"),
            service_manager_headers,
        )
        site = validate_success(res, 201)
        assert_customer_site(site)
        assert site["contract_discount_pct"] == 0
        assert site["capital_threshold_cents"] == 500000
        assert site["credit_hold"] is False
        assert site["site_posture"] == "NORMAL"
        assert site["version"] == 1

        fetched = validate_success(
            api.get_site(site["id"], service_manager_headers), 200
        )
        assert fetched["id"] == site["id"]
        assert fetched["contract_discount_pct"] == 0
        assert fetched["capital_threshold_cents"] == 500000
        assert fetched["credit_hold"] is False
        assert fetched["site_posture"] == "NORMAL"

    def test_site_creation_missing_required_returns_validation(
        self, api, service_manager_headers
    ):
        """PRD §2.10: "The request body is then checked for structural validity
        (required fields present, types correct, enum values in range, numeric
        ranges respected, no unknown fields) and any violation yields
        `ERR_VALIDATION`."
        PRD §3.1: "A `ServiceManager` onboards a customer site by creating a
        `CustomerSite` with a display `name` and a two-letter `state_code`."

        Design: Corner/entities/site_creation_missing_required_returns_validation
        """
        res = api.create_site({}, service_manager_headers)
        validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)

    def test_site_create_extra_field_rejected(self, api, service_manager_headers):
        """PRD §2.10: "The request body is then checked for structural validity
        (required fields present, types correct, enum values in range, numeric
        ranges respected, no unknown fields) and any violation yields
        `ERR_VALIDATION`."

        Design: Corner/entities/site_create_extra_field_rejected
        """
        res = api.create_site(
            {
                "name": "X",
                "state_code": "IA",
                "id": "00000000-0000-0000-0000-0000000000aa",
            },
            service_manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)


class TestVesselCreation:
    def test_vessel_creation_computed_fields_initialized(
        self, api, service_manager_headers
    ):
        """PRD §3.1: "On creation the vessel's `current_inventory_tons` is set equal
        to `opening_inventory_tons`, `flow_posture` starts at `NORMAL`, and
        `scale_status` starts at `IN_TOLERANCE`."
        PRD §3.1: "Reorder behaviour is configured through `reorder_point_pct`
        (0–100), an optional `target_fill_pct` (default 90, must be greater than
        zero and at most 100), an optional `replenishment_policy` of `TARGET_FILL`
        (default) or `DAYS_OF_COVER`, an optional `cover_days` (default 7, must be
        greater than zero), and an optional `default_usage_tons` (default 1.0, must
        be at least zero) used as a fallback when fewer than two readings exist in
        the trailing usage window."
        PRD §3.1: "Quality monitoring is configured via `moisture_limit_pct`
        (default 12.0, range 0–100). Scale-calibration behaviour is configured via
        `error_basis` — `OF_READING` (default) or `OF_FULL_SCALE` — and
        `full_scale_tons`, which is required when `error_basis` is `OF_FULL_SCALE`
        and ignored otherwise."

        Design: Corner/entities/vessel_creation_computed_fields_initialized
        """
        site = validate_success(
            api.create_site(
                create_site_payload(name="V Site", state_code="IA"),
                service_manager_headers,
            ),
            201,
        )
        res = api.create_vessel(
            create_vessel_payload(
                site["id"],
                name="BIN-1",
                vessel_kind="BIN",
                capacity_tons=50,
                material_name="salt",
                reorder_point_pct=20,
                opening_inventory_tons=12.5,
            ),
            service_manager_headers,
        )
        vessel = validate_success(res, 201)
        assert vessel["current_inventory_tons"] == 12.5
        assert vessel["flow_posture"] == "NORMAL"
        assert vessel["scale_status"] == "IN_TOLERANCE"
        assert vessel["replenishment_policy"] == "TARGET_FILL"
        assert vessel["target_fill_pct"] == 90
        assert vessel["cover_days"] == 7
        assert vessel["default_usage_tons"] == 1.0
        assert vessel["moisture_limit_pct"] == 12.0
        assert vessel["error_basis"] == "OF_READING"

    def test_vessel_invalid_enum_kind_rejected(self, api, service_manager_headers):
        """PRD §2.10: "The request body is then checked for structural validity
        (required fields present, types correct, enum values in range, numeric
        ranges respected, no unknown fields) and any violation yields
        `ERR_VALIDATION`."
        PRD §3.1: "a `vessel_kind` of `SILO`, `BIN`, or `HOPPER`"

        Design: Corner/entities/vessel_invalid_enum_kind_rejected
        """
        site = validate_success(
            api.create_site(
                create_site_payload(name="Enum Site", state_code="IA"),
                service_manager_headers,
            ),
            201,
        )
        res = api.create_vessel(
            create_vessel_payload(
                site["id"],
                name="X",
                vessel_kind="PYRAMID",
                capacity_tons=50,
                material_name="salt",
                reorder_point_pct=20,
            ),
            service_manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)

    def test_vessel_create_computed_field_input_rejected(
        self, api, service_manager_headers
    ):
        """PRD §2.10: "The request body is then checked for structural validity
        (required fields present, types correct, enum values in range, numeric
        ranges respected, no unknown fields) and any violation yields
        `ERR_VALIDATION`."

        Design: Corner/entities/vessel_create_computed_field_input_rejected
        """
        site = validate_success(
            api.create_site(
                create_site_payload(name="CF Site", state_code="IA"),
                service_manager_headers,
            ),
            201,
        )
        payload = create_vessel_payload(
            site["id"],
            name="BIN-9",
            vessel_kind="BIN",
            capacity_tons=50,
            material_name="salt",
            reorder_point_pct=20,
        )
        payload["flow_posture"] = "FLOW_IMPAIRED"
        res = api.create_vessel(payload, service_manager_headers)
        validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)


class TestLevelReadingShape:
    def test_level_reading_out_of_range_rejected(self, api, service_manager_headers):
        """PRD §3.2: "A `PlantOperator` (for vessels of its own site only) or a
        `Technician` records a `LevelReading` by supplying `vessel_id`,
        `measured_at` (ISO 8601 UTC), and `level_pct` (0–100 inclusive)."
        PRD §2.10: "The request body is then checked for structural validity
        (required fields present, types correct, enum values in range, numeric
        ranges respected, no unknown fields) and any violation yields
        `ERR_VALIDATION`."

        Design: Corner/entities/level_reading_out_of_range_rejected
        """
        site = validate_success(
            api.create_site(
                create_site_payload(name="Range Site", state_code="IA"),
                service_manager_headers,
            ),
            201,
        )
        vessel = validate_success(
            api.create_vessel(
                create_vessel_payload(
                    site["id"],
                    name="SILO-1",
                    capacity_tons=100,
                    material_name="corn",
                    reorder_point_pct=30,
                ),
                service_manager_headers,
            ),
            201,
        )
        res = api.create_level_reading(
            {
                "vessel_id": vessel["id"],
                "measured_at": "2026-08-02T00:00:00Z",
                "level_pct": 101,
            },
            make_plant_operator_headers(site["id"]),
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)

    def test_reading_immutable_event_shape(self, api, service_manager_headers):
        """PRD §2.6: "Sub-resources `LevelReading`, `MaterialQualityReport`, and
        `ScaleCalibration` are immutable measurement records; they carry only `id`
        and `created_at`. Neither `updated_at` nor `version` is present on those
        entities."

        Design: Corner/entities/reading_immutable_event_shape
        """
        site = validate_success(
            api.create_site(
                create_site_payload(name="Imm Site", state_code="IA"),
                service_manager_headers,
            ),
            201,
        )
        vessel = validate_success(
            api.create_vessel(
                create_vessel_payload(
                    site["id"],
                    name="SILO-2",
                    capacity_tons=100,
                    material_name="corn",
                    reorder_point_pct=30,
                ),
                service_manager_headers,
            ),
            201,
        )
        res = api.create_level_reading(
            {
                "vessel_id": vessel["id"],
                "measured_at": "2026-08-02T00:00:00Z",
                "level_pct": 55.0,
            },
            make_plant_operator_headers(site["id"]),
        )
        reading = validate_success(res, 201)
        assert "id" in reading and "created_at" in reading
        assert "version" not in reading, "LevelReading must not carry version"
        assert "updated_at" not in reading, "LevelReading must not carry updated_at"

        data, meta = validate_paginated(
            api.list_level_readings(vessel["id"], service_manager_headers)
        )
        assert meta["total_count"] == 1
        assert data[0]["id"] == reading["id"]
