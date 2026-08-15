"""Appliance load intake, load calculation, OCC, and the LOAD_CONFIRMED freeze."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_appliance_load_payload,
    get_success_data,
    make_builder_headers,
    setup_draft_app,
    setup_load_confirmed_app,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSubmitLoadBoundary:
    def test_submit_with_zero_loads_rejected(self, api, rep_headers):
        """PRD §3.1: "Submitting requires that the acting builder own the application (`ERR_FORBIDDEN_OWNER`), that the builder still be `ACTIVE`, and that at least one appliance load row exist — an empty load sheet is rejected with `ERR_NO_APPLIANCE_LOADS` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/submit_with_zero_loads_rejected
        """
        ctx = setup_draft_app()
        resp = api.submit_application(ctx["app"]["id"], ctx["builder_headers"])
        validate_error(resp, ApiErrorId.ERR_NO_APPLIANCE_LOADS, expected_status=422)

        after = get_success_data(
            api.get_service_application(ctx["app"]["id"], rep_headers)
        )
        assert after["status"] == "DRAFT", "rejected submit must leave the application DRAFT"

    def test_submit_with_one_load_succeeds(self, api, rep_headers):
        """PRD §3.1: "A successful submission moves the application from `DRAFT` to `SUBMITTED`, stamps `submitted_at`, and runs the load calculation, persisting three computed figures on the application."
        PRD §3.1: "`diversity_adjusted_load_cfph` applies a coincidence factor that depends only on the row count: exactly one row keeps the full connected load (factor 1.00); two or three rows take 0.85; four, five, or six rows take 0.75; seven or more rows take 0.65 — the connected load multiplied by the applicable factor, again rounded half up to one decimal place."

        Design: Difficulty/boundary_precision_check/submit_with_zero_loads_rejected
        """
        ctx = setup_draft_app(
            loads=[{"appliance_type": "FURNACE", "quantity": 1, "btuh_input_rating": 80000}]
        )
        resp = api.submit_application(ctx["app"]["id"], ctx["builder_headers"])
        submitted = validate_success(resp)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["appliance_count"] == 1, (
            f"appliance_count counts rows: expected 1, got {submitted['appliance_count']}"
        )
        assert submitted["total_connected_load_cfph"] == pytest.approx(80.0)
        assert submitted["diversity_adjusted_load_cfph"] == pytest.approx(80.0), (
            "a single row keeps the full connected load (factor 1.00)"
        )


class TestLoadCalculation:
    def test_diversity_factor_tier_applied(self, api, rep_headers):
        """PRD §3.1: "`total_connected_load_cfph` is the sum of every row's `counted_load_cfph`, rounded half up to one decimal place."
        PRD §3.1: "`diversity_adjusted_load_cfph` applies a coincidence factor that depends only on the row count: exactly one row keeps the full connected load (factor 1.00); two or three rows take 0.85; four, five, or six rows take 0.75; seven or more rows take 0.65 — the connected load multiplied by the applicable factor, again rounded half up to one decimal place."
        PRD §3.1: "The system computes each row's `counted_load_cfph`: the quantity multiplied by the nameplate rating, divided by one thousand BTU per hour per cubic foot per hour, rounded half up to one decimal place — and recomputes that figure whenever the row is created or edited."

        Design: Corner/calculations/diversity_factor_tier_applied
        """
        ctx = setup_draft_app(
            loads=[
                {"appliance_type": "FURNACE", "quantity": 1, "btuh_input_rating": 80000},
                {"appliance_type": "WATER_HEATER", "quantity": 1, "btuh_input_rating": 40000},
                {"appliance_type": "RANGE", "quantity": 1, "btuh_input_rating": 65000},
                {"appliance_type": "DRYER", "quantity": 1, "btuh_input_rating": 35000},
            ]
        )
        expected_counted = [80.0, 40.0, 65.0, 35.0]
        for load, expected in zip(ctx["loads"], expected_counted):
            assert load["counted_load_cfph"] == pytest.approx(expected), (
                f"row counted_load_cfph expected {expected}, got {load['counted_load_cfph']}"
            )

        resp = api.submit_application(ctx["app"]["id"], ctx["builder_headers"])
        submitted = validate_success(resp)
        assert submitted["appliance_count"] == 4
        assert submitted["total_connected_load_cfph"] == pytest.approx(220.0)
        assert submitted["diversity_adjusted_load_cfph"] == pytest.approx(165.0), (
            f"4 rows fall in the 0.75 tier: 220.0 x 0.75 = 165.0, "
            f"got {submitted['diversity_adjusted_load_cfph']}"
        )

    def test_load_patch_recomputes_counted_load(self, api):
        """PRD §3.1: "The system computes each row's `counted_load_cfph`: the quantity multiplied by the nameplate rating, divided by one thousand BTU per hour per cubic foot per hour, rounded half up to one decimal place — and recomputes that figure whenever the row is created or edited."
        PRD §2.4: "`version` (integer): starts as a small integer and increments by one on every mutation of the resource — including system-driven mutations caused by cascades from other resources, not just direct client writes."

        Design: Corner/calculations/load_patch_recomputes_counted
        """
        ctx = setup_draft_app(
            loads=[{"appliance_type": "FURNACE", "quantity": 1, "btuh_input_rating": 80000}]
        )
        load = ctx["loads"][0]
        assert load["counted_load_cfph"] == pytest.approx(80.0)

        resp = api.patch_appliance_load(
            load["id"],
            {"expected_load_version": load["version"], "quantity": 2},
            ctx["builder_headers"],
        )
        patched = validate_success(resp)
        assert patched["counted_load_cfph"] == pytest.approx(160.0), (
            f"2 x 80000 / 1000 = 160.0, got {patched['counted_load_cfph']}"
        )
        assert patched["version"] == load["version"] + 1


class TestLoadsLocked:
    def test_loads_locked_after_confirm_load(self, api, rep_headers):
        """PRD §3.1: "Once the application reaches `LOAD_CONFIRMED`, every load write — create, edit, or delete — is rejected with `ERR_LOADS_LOCKED` (HTTP 409)."

        Design: Corner/errors/loads_locked_after_confirm_rejected
        """
        ctx = setup_load_confirmed_app(
            loads=[{"appliance_type": "FURNACE", "quantity": 1, "btuh_input_rating": 80000}]
        )
        app_id = ctx["app"]["id"]
        load = ctx["loads"][0]

        resp = api.create_appliance_load(
            {
                "service_application_id": app_id,
                "appliance_type": "DRYER",
                "quantity": 1,
                "btuh_input_rating": 35000,
            },
            ctx["builder_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_LOADS_LOCKED, expected_status=409)

        resp = api.patch_appliance_load(
            load["id"],
            {"expected_load_version": load["version"], "quantity": 2},
            ctx["builder_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_LOADS_LOCKED, expected_status=409)

        resp = api.delete_appliance_load(load["id"], ctx["builder_headers"])
        validate_error(resp, ApiErrorId.ERR_LOADS_LOCKED, expected_status=409)

        list_resp = api.list_appliance_loads(
            rep_headers, params={"service_application_id": app_id}
        )
        data, meta = validate_paginated(list_resp)
        assert meta["total_count"] == 1, "the frozen load set must be unchanged"
        assert data[0]["quantity"] == 1


class TestLoadValidation:
    def test_missing_required_btuh_rating_rejected(self, api, rep_headers):
        """PRD §2.6: "Separately from this ordered stack, malformed request bodies — a missing required field, a value of the wrong type, an enum member outside the declared set, a non-positive quantity, footage, or money amount, a time window whose end does not fall strictly after its start, or a road-cut permit with an empty crossing list — are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "Each appliance load row carries the application's `service_application_id`, an `appliance_type` drawn from `FURNACE`, `WATER_HEATER`, `RANGE`, `DRYER`, `FIREPLACE`, `STANDBY_GENERATOR`, `POOL_HEATER`, or `OTHER`, a `quantity` of at least one, and a per-unit nameplate `btuh_input_rating` greater than zero."

        Design: Corner/entities/load_missing_required_field_rejected
        """
        ctx = setup_draft_app()
        payload = create_appliance_load_payload(ctx["app"]["id"])
        del payload["btuh_input_rating"]
        resp = api.create_appliance_load(payload, ctx["builder_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        list_resp = api.list_appliance_loads(
            rep_headers, params={"service_application_id": ctx["app"]["id"]}
        )
        _, meta = validate_paginated(list_resp)
        assert meta["total_count"] == 0, "rejected load must not be persisted"

    def test_load_with_unknown_application_not_found(self, api):
        """PRD §2.10: "References are resolved in a fixed left-to-right order: path identifiers first, then body foreign-key fields in their declared order. The first unresolved reference aborts the request with the 404 specific to that entity"

        Design: Corner/entities/load_with_unknown_application_not_found
        """
        from test_helpers import NON_EXISTENT_UUID
        bogus_headers = make_builder_headers(NON_EXISTENT_UUID)
        resp = api.create_appliance_load(
            {
                "service_application_id": NON_EXISTENT_UUID,
                "appliance_type": "FURNACE",
                "quantity": 1,
                "btuh_input_rating": 80000,
            },
            bogus_headers,
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND, expected_status=404)


class TestOptimisticConcurrency:
    def test_appliance_load_stale_version_rejected(self, api):
        """PRD §2.7: "Editing an appliance load requires the body to carry `expected_load_version` equal to that load's current `version`."
        PRD §2.7: "In all three cases, if the supplied value does not match the entity's current `version` — because another writer has advanced it since the client last read the entity — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than overwriting state the client never observed."

        Design: Corner/complexity_layers/appliance_load_occ_stale_rejected
        """
        ctx = setup_draft_app(
            loads=[{"appliance_type": "FURNACE", "quantity": 1, "btuh_input_rating": 80000}]
        )
        load = ctx["loads"][0]
        observed_version = load["version"]

        resp = api.patch_appliance_load(
            load["id"],
            {"expected_load_version": observed_version, "quantity": 2},
            ctx["builder_headers"],
        )
        patched = validate_success(resp)
        assert patched["version"] == observed_version + 1
        assert patched["counted_load_cfph"] == pytest.approx(160.0)

        resp = api.patch_appliance_load(
            load["id"],
            {"expected_load_version": observed_version, "btuh_input_rating": 90000},
            ctx["builder_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        after = get_success_data(
            api.get_appliance_load(load["id"], ctx["builder_headers"])
        )
        assert after["btuh_input_rating"] == 80000, "the stale write must be discarded"

    def test_application_patch_stale_version_rejected(self, api):
        """PRD §2.7: "Editing a draft application's header requires `expected_application_version` equal to the application's current `version`."
        PRD §2.7: "In all three cases, if the supplied value does not match the entity's current `version` — because another writer has advanced it since the client last read the entity — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than overwriting state the client never observed."

        Design: Corner/complexity_layers/application_patch_stale_rejected
        """
        ctx = setup_draft_app()
        app = ctx["app"]
        observed_version = app["version"]

        resp = api.patch_service_application(
            app["id"],
            {"expected_application_version": observed_version, "city": "Chatham"},
            ctx["builder_headers"],
        )
        patched = validate_success(resp)
        assert patched["city"] == "Chatham"
        assert patched["version"] == observed_version + 1

        resp = api.patch_service_application(
            app["id"],
            {"expected_application_version": observed_version, "postal_code": "62702"},
            ctx["builder_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        after = get_success_data(
            api.get_service_application(app["id"], ctx["builder_headers"])
        )
        assert after["postal_code"] == "62701", "the stale write must be discarded"
