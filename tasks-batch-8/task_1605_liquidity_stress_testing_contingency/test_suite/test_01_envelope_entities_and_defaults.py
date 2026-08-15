"""Envelope shape, entity creation defaults, computed fields, type constraints.

Covers corner-design instances for entity creation, defaults, computed
fields, immutability, not-found, listing, and envelope shape.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_ewi_metric,
    assert_liquid_asset,
    assert_metric_reading,
    assert_stress_scenario,
    create_ewi_metric_payload,
    create_liquid_asset_payload,
    create_scenario_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_analyst_headers,
    make_asset,
    make_metric,
    make_scenario,
    post_reading,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST_HEADERS = make_analyst_headers("ta_1")


class TestEnvelopeShape:
    def test_create_scenario_success_envelope(self, api, officer_headers):
        """PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format in their JSON body" with
        meta.api_request_id, meta.api_request_timestamp, response_type and data.
        PRD §4: "Operations that create a new resource return HTTP 201".

        Design: Corner/endpoints/response_envelope_object_shape
        """
        resp = api.create_scenario(
            create_scenario_payload(name="Base", tier="BASELINE"), officer_headers,
        )
        assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text}"
        body = resp.json()
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"], (
            "meta.api_request_id must be a non-empty string"
        )
        assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
            "meta.api_request_timestamp must be an ISO 8601 timestamp"
        )
        assert body["response_type"] == "object", (
            f"single-resource create must return response_type object, got {body['response_type']!r}"
        )
        assert isinstance(body["data"].get("id"), str) and body["data"]["id"], (
            "data.id must be present on a created resource"
        )


class TestScenarioCreation:
    def test_scenario_creation_applies_system_defaults(self, api, officer_headers):
        """PRD §3.1: "A new scenario starts `ACTIVE` with its `run_count` at zero."
        PRD §2.5: "Every persisted resource has an `id` — a server-minted UUID
        used for identity only, carrying no type prefix — and a `created_at`
        timestamp. Resources other than the three append-only event types also
        carry `updated_at` and an integer `version`."

        Design: Corner/entities/scenario_creation_applies_system_defaults
        """
        resp = api.create_scenario(
            create_scenario_payload(
                name="Base", tier="BASELINE", deposit_runoff_pct=5,
                wholesale_renewal_pct=80, level2_addon_bps=0, horizon_days=30,
            ),
            officer_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_stress_scenario(data)
        assert data["status"] == "ACTIVE", f"new scenario must start ACTIVE, got {data['status']}"
        assert data["run_count"] == 0, f"new scenario run_count must be 0, got {data['run_count']}"
        assert data["version"] == 1, f"new scenario version must be 1, got {data['version']}"
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])

    def test_scenario_list_paginates(self, api, officer_headers, analyst_headers):
        """PRD §2.3: "List endpoints accept the query parameters `limit` and
        `offset`."
        PRD §2.3: "List responses carry the pagination fields `limit`,
        `offset`, `total_count`, and `has_more` inside `meta`."

        Design: Corner/entities/scenario_list_paginates
        """
        make_scenario(name="B", tier="BASELINE")
        make_scenario(name="M", tier="MODERATE", deposit_runoff_pct=10,
                      wholesale_renewal_pct=50, level2_addon_bps=500, horizon_days=10)
        make_scenario(name="S", tier="SEVERE", deposit_runoff_pct=25,
                      wholesale_renewal_pct=0, level2_addon_bps=1000)
        resp = api.list_scenarios(analyst_headers, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 2, f"limit=2 must return exactly 2 entries, got {len(data)}"
        assert meta["total_count"] == 3, f"total_count must be 3, got {meta['total_count']}"
        assert meta["has_more"] is True, "has_more must be true when a page remains"


class TestEwiMetricDefaults:
    def test_ewi_metric_defaults_applied(self, api, officer_headers, analyst_headers):
        """PRD §3.6: "and optionally `min_reading_interval_hours`, which
        defaults to zero and means no cadence rule."
        PRD §3.6: "A new metric starts with `current_band` at `GREEN` and
        `last_reading_at` empty."

        Design: Corner/entities/ewi_metric_defaults_applied
        """
        payload = create_ewi_metric_payload(code="M", name="m")
        del payload["min_reading_interval_hours"]  # omitted entirely -> server default
        resp = api.create_ewi_metric(payload, officer_headers)
        data = validate_success(resp, expected_status=201)
        assert_ewi_metric(data)
        assert data["min_reading_interval_hours"] == 0, (
            f"omitted min_reading_interval_hours must default to 0, got {data['min_reading_interval_hours']}"
        )
        assert data["current_band"] == "GREEN", f"new metric band must be GREEN, got {data['current_band']}"
        assert data.get("last_reading_at") is None, "new metric last_reading_at must be empty"

        got = validate_success(api.get_ewi_metric(data["id"], officer_headers))
        assert got["current_band"] == "GREEN", "GET single must agree on GREEN band"

        listed, meta = validate_paginated(api.list_ewi_metrics(analyst_headers))
        assert len(listed) == 1, f"exactly one metric must be listed, got {len(listed)}"
        assert meta["total_count"] == 1


class TestLiquidAssetCreation:
    def test_asset_haircut_computed_by_class(self, api, ops_headers):
        """PRD §3.3: "The class determines the `haircut_bps` the system derives:
        zero for `LEVEL_1`, 1500 basis points (fifteen percent) for `LEVEL_2A`,
        and 2500 basis points (twenty-five percent) for `LEVEL_2B`. Assets
        arrive `UNENCUMBERED`".

        Design: Corner/entities/asset_haircut_computed_by_class
        """
        resp = api.create_liquid_asset(
            create_liquid_asset_payload(
                asset_class="LEVEL_2B", reference="B1", market_value_cents=1_000_000,
            ),
            ops_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_liquid_asset(data)
        assert data["haircut_bps"] == 2500, (
            f"LEVEL_2B haircut must be 2500 bps, got {data['haircut_bps']}"
        )
        assert data["encumbrance_status"] == "UNENCUMBERED", (
            f"assets arrive UNENCUMBERED, got {data['encumbrance_status']}"
        )

    def test_asset_invalid_enum_rejected(self, api, ops_headers):
        """PRD §2.9: "Fourth, request shape: required fields present, types
        valid, enum membership respected, numeric ranges honored, and
        cross-field rules such as threshold coherence (`ERR_INVALID_REQUEST`,
        `ERR_THRESHOLD_CONFIG_INVALID`)".

        Design: Corner/entities/asset_invalid_enum_rejected
        """
        resp = api.create_liquid_asset(
            create_liquid_asset_payload(
                asset_class="LEVEL_3", reference="X", market_value_cents=1000,
            ),
            ops_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestReadingImmutability:
    def test_reading_append_only_without_version(self, api, analyst_headers):
        """PRD §2.5: "The append-only event types — metric readings, posture
        snapshots, and intraday snapshots — carry only `id` and `created_at`.
        Both `updated_at` and `version` are absent from them, because an event,
        once recorded, is never modified."

        Design: Corner/entities/reading_append_only_without_version
        """
        metric = make_metric(code="M", name="m")
        resp = api.post_metric_reading(
            metric["id"], {"observed_at": "2026-08-01T00:00:00Z", "value": 100},
            analyst_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_metric_reading(data)
        assert data["band"] == "GREEN", f"value 100 below amber 1000 must be GREEN, got {data['band']}"


class TestNotFound:
    def test_get_breach_not_found_returns_error_envelope(self, api, officer_headers):
        """PRD §2.8: "the first identifier that does not resolve to an existing
        resource yields `ERR_NOT_FOUND` (HTTP 404)".
        PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with response_type "error" and data.error_id.

        Design: Corner/entities/get_breach_not_found_returns_error_envelope
        """
        resp = api.get_breach(NON_EXISTENT_UUID, officer_headers)
        assert resp.status_code == 404, f"expected 404, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body.get("response_type") == "error", (
            f"error envelope must carry response_type error, got {body.get('response_type')!r}"
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
