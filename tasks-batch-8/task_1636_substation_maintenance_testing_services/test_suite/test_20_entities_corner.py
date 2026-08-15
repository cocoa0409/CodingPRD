"""Corner coverage — entities: creation defaults, computed fields, required
inputs, enum vocabularies, existence, uniqueness, and listing pagination."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_substation,
    create_asset_payload,
    create_certified_technician,
    create_outage_window,
    create_policy,
    create_substation,
    get_success_data,
    is_valid_uuid,
    setup_asset,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["ops_manager_headers"]
COORD = TEST_USERS["coordinator_headers"]


class TestSubstationCreationDefaults:
    def test_substation_creation_applies_defaults(self):
        """PRD §3.1: "A substation is registered with a `name`, a `code` unique
        across all substations, and a `region`; it arrives in `ACTIVE` status
        and may later be decommissioned to `DECOMMISSIONED`."
        PRD §2.4: "Every persisted entity carries `id` (a server-minted UUID
        with no type prefix), `created_at` (ISO 8601 UTC with three fractional
        digits), `updated_at` (same format, refreshed on every mutation), and
        `version` (an integer that increments by exactly 1 on every state
        transition and on every mutation the platform applies to that row)."

        Design: Corner/entities/substation_creation_defaults_applied
        """
        created = validate_success(
            api_client.create_substation(
                {"name": "Sub G", "code": "SUB-G", "region": "North"}, OPS
            ),
            201,
        )
        assert_substation(created)
        assert created["status"] == "ACTIVE"
        assert is_valid_uuid(created["id"])
        rows, meta = validate_paginated(api_client.list_substations(OPS))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == created["id"]


class TestAssetComputedFieldsAndDefaults:
    def test_computed_condition_score_ignores_client_input(self):
        """PRD §3.1: "The new asset arrives in `IN_SERVICE` status with
        `condition_score` initialized to 100.00 and `next_due_date` computed
        from the condition-adjusted variant described in §3.5."
        PRD §3.1: "The caller supplies `asset_class`, `voltage_kv`,
        `install_date`, and optionally `criticality` (default `MEDIUM`; one of
        `HIGH`, `MEDIUM`, `LOW`), `nameplate_mva` (required in practice for
        `POWER_TRANSFORMER`), `last_maintenance_completed_at`, and
        `upstream_asset_id`."

        Design: Corner/entities/asset_computed_condition_score_input_ignored
        """
        base_sub = create_substation()
        create_policy("POWER_TRANSFORMER")
        payload = create_asset_payload(base_sub["id"], "POWER_TRANSFORMER")
        payload["condition_score"] = 5  # computed field — must not be honored
        created = validate_success(api_client.create_asset(payload, OPS), 201)
        assert abs(created["condition_score"] - 100.00) < 1e-9
        assert created["criticality"] == "MEDIUM"
        assert created["status"] == "IN_SERVICE"


class TestAssetSchemaValidation:
    def test_missing_required_voltage_rejected(self):
        """PRD §3.1: "The caller supplies `asset_class`, `voltage_kv`,
        `install_date`, and optionally `criticality` (default `MEDIUM`; one of
        `HIGH`, `MEDIUM`, `LOW`), `nameplate_mva` (required in practice for
        `POWER_TRANSFORMER`), `last_maintenance_completed_at`, and
        `upstream_asset_id`."
        PRD §2.8: "then request-body schema and field-type checks (HTTP 400)"

        Design: Corner/entities/asset_missing_required_field_returns_invalid_request
        """
        sub = create_substation()
        create_policy("POWER_TRANSFORMER")
        resp = api_client.create_asset(
            {
                "substation_id": sub["id"],
                "asset_class": "POWER_TRANSFORMER",
                "install_date": "2022-01-01T00:00:00Z",
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)

    def test_invalid_asset_class_enum_rejected(self):
        """PRD §3.1: "Each policy names its `asset_class` (one of
        `POWER_TRANSFORMER`, `CIRCUIT_BREAKER`, `RELAY`; the class label is
        unique across policies)".
        PRD §2.8: "then request-body schema and field-type checks (HTTP 400)"

        Design: Corner/entities/asset_invalid_enum_rejected
        """
        sub = create_substation()
        resp = api_client.create_asset(
            {
                "substation_id": sub["id"],
                "asset_class": "FUSION_REACTOR",
                "voltage_kv": 115,
                "install_date": "2022-01-01T00:00:00Z",
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


class TestAssetExistence:
    def test_get_asset_not_found(self):
        """PRD §2.8: "then path-id resolution, left-to-right along nested URL
        segments (HTTP 404)"
        PRD §2.9: "Where a URL nests one resource under another (a switching
        step under its outage window, a certification under its technician, an
        environmental inspection under its substation), path identifiers
        resolve left-to-right. A failure at any segment produces
        `ERR_NOT_FOUND` (HTTP 404) before the request proceeds to deeper
        validation."

        Design: Corner/entities/get_asset_not_found_returns_404
        """
        resp = api_client.get_asset(NON_EXISTENT_UUID, OPS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_asset_creation_without_policy_rejected(self):
        """PRD §3.1: "The platform refuses to register an asset whose class has
        no `AssetClassPolicy` with `ERR_POLICY_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/asset_missing_policy_returns_policy_not_found
        """
        sub = create_substation()
        resp = api_client.create_asset(
            {
                "substation_id": sub["id"],
                "asset_class": "CIRCUIT_BREAKER",
                "voltage_kv": 34.5,
                "install_date": "2021-01-01T00:00:00Z",
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_POLICY_NOT_FOUND, 404)

    def test_body_fk_reference_not_found(self):
        """PRD §2.8: "then foreign-key resolution for ids supplied in the body
        (HTTP 404)"

        Design: Corner/entities/fk_body_reference_returns_not_found
        """
        _, tech_headers = create_certified_technician("NETA_LEVEL_2")
        resp = api_client.create_test_event(
            {
                "asset_id": NON_EXISTENT_UUID,
                "test_type": "OIL_MOISTURE",
                "value_primary": 10,
                "measured_at": "2026-07-01T00:00:00Z",
            },
            tech_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestAssetListPagination:
    def test_default_limit_and_offset_pagination(self):
        """PRD §2.3: "List endpoints accept `limit` and `offset` query
        parameters. The default `limit` is 10, the minimum is 1, the maximum is
        100, and the default `offset` is 0. Results are sorted by `created_at`
        ascending. The `meta` block of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/asset_list_pagination_defaults
        """
        base = setup_asset("POWER_TRANSFORMER")
        for day in range(2, 13):  # 1 (from setup) + 11 = 12 assets total
            get_success_data(
                api_client.create_asset(
                    {
                        "substation_id": base["substation"]["id"],
                        "asset_class": "POWER_TRANSFORMER",
                        "voltage_kv": 115,
                        "install_date": f"2020-01-{day:02d}T00:00:00Z",
                    },
                    OPS,
                )
            )
        page1, meta1 = validate_paginated(api_client.list_assets(OPS))
        assert len(page1) == 10
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(api_client.list_assets(OPS, params={"offset": 10}))
        assert len(page2) == 2
        assert meta2["offset"] == 10
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False


class TestUniqueness:
    def test_duplicate_substation_code_rejected(self):
        """PRD §3.1: "Creating a second policy for a class that already has one
        is rejected with `ERR_DUPLICATE_KEY` (HTTP 409), as is creating a
        second substation with the same `code` or a second technician with the
        same `employee_code`."

        Design: Corner/entities/duplicate_substation_code_rejected
        """
        create_substation(name="First", code="SUB-DUP")
        resp = api_client.create_substation(
            {"name": "Second", "code": "SUB-DUP", "region": "South"}, OPS
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY, 409)

    def test_duplicate_step_sequence_within_window_rejected(self):
        """PRD §3.3: "An `OutageCoordinator` adds steps while the window is
        `REQUESTED` or `APPROVED` by supplying `sequence_no` (an integer at
        least 1, unique within the window — duplicates are rejected with
        `ERR_DUPLICATE_KEY`, HTTP 409) and a free-text `description`."

        Design: Corner/entities/duplicate_step_sequence_rejected
        """
        base = setup_asset("POWER_TRANSFORMER")
        window = create_outage_window(
            base["substation"]["id"], base["asset"]["id"],
            "2026-09-15T08:00:00Z", "2026-09-15T16:00:00Z", purpose="Steps",
        )
        validate_success(
            api_client.create_switching_step(
                window["id"], {"sequence_no": 1, "description": "Step one"}, COORD
            ),
            201,
        )
        resp = api_client.create_switching_step(
            window["id"], {"sequence_no": 1, "description": "Duplicate sequence"}, COORD
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY, 409)
