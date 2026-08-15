"""Response envelope, customer/asset/repair-order creation rules, and listing."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_asset,
    assert_customer,
    assert_repair_order,
    create_asset,
    create_asset_payload,
    create_customer,
    create_customer_payload,
    create_repair_order,
    create_repair_order_payload,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

SM = TEST_USERS["service_manager_headers"]
IC = TEST_USERS["intake_coordinator_headers"]


class TestResponseEnvelope:
    def test_envelope_shape_on_object_list_and_error(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
        PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        customer = create_customer(name="Briscoe", account_number="BR-360",
                                   credit_limit_cents=500000, warranty_terms_days=365)

        # Single-resource read: object envelope with request meta.
        single = api.get_customer(customer["id"], SM)
        assert single.status_code == 200
        body = single.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["data"]["id"] == customer["id"]

        # List read: array envelope with pagination fields at their defaults.
        listed = api.list_customers(SM)
        assert listed.status_code == 200
        lbody = listed.json()
        assert lbody["response_type"] == "array"
        assert lbody["meta"]["limit"] == 10, "limit defaults to 10"
        assert lbody["meta"]["offset"] == 0, "offset defaults to 0"
        assert isinstance(lbody["meta"]["total_count"], int)
        assert isinstance(lbody["meta"]["has_more"], bool)

        # Error read: error envelope with a trimmed meta object.
        missing = api.get_customer(NON_EXISTENT_UUID, SM)
        assert missing.status_code == 404
        ebody = missing.json()
        assert ebody["response_type"] == "error"
        assert ebody["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(ebody["data"]["message"], str) and ebody["data"]["message"].strip()
        assert set(ebody["meta"].keys()) == {"api_request_id", "api_request_timestamp"}


class TestCustomerCreation:
    def test_customer_defaults_and_required_fields(self, api):
        """PRD §3.1: "The `pool_program` flag marks participation in the rotable spare pool program and defaults to false when omitted."
        PRD §3.1: "At onboarding the customer's `pool_available_count` starts at zero; thereafter it counts the customer's pool units whose `pool_status` is `IN_POOL` or `RESERVED` — `ISSUED` and `WITHDRAWN` units are not available — and is recomputed whenever a unit is enrolled, issued, or withdrawn."
        PRD §2.6: "2. **Request-body shape** — required fields present, enum values valid, date and datetime formats valid, and the conditional nameplate fields present per equipment class (`ERR_VALIDATION`, HTTP 400)."

        Design: Corner/entities/customer_creation_defaults_and_required_fields
        """
        resp = api.create_customer(
            create_customer_payload(name="Alta Gas", account_number="AG-100",
                                    credit_limit_cents=500000, warranty_terms_days=365),
            SM,
        )
        customer = validate_success(resp, 201)
        assert_customer(customer)
        assert customer["pool_program"] is False, "pool_program defaults to false"
        assert customer["pool_available_count"] == 0

        bad = api.create_customer(
            {"name": "Broken Account", "credit_limit_cents": 100, "warranty_terms_days": 30},
            SM,
        )
        validate_error(bad, ApiErrorId.ERR_VALIDATION)

    def test_customer_system_fields_stamped_at_creation(self, api):
        """PRD §2.4: "At startup the clock reads exactly `2026-08-01T00:00:00Z`; until it is explicitly set, every read of the current instant returns this default."
        PRD §2.5: "`created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created."
        PRD §2.5: "`id` is a server-minted UUID with no type prefix."
        PRD §2.5: "`version` is an integer that increments by one with every mutation of the resource."

        Design: Corner/entities/system_fields_stamped_at_creation
        """
        resp = api.create_customer(
            create_customer_payload(name="Fern Ridge", account_number="FR-150",
                                    credit_limit_cents=500000, warranty_terms_days=365),
            SM,
        )
        customer = validate_success(resp, 201)
        assert customer["created_at"] == "2026-08-01T00:00:00.000Z", (
            "created_at stamps the logical clock's startup default, rendered "
            "with the three fractional digits §2.5 mandates"
        )
        assert customer["version"] == 1, "a freshly created resource carries version 1"
        assert is_valid_uuid(customer["id"]), "id is a type-prefix-free UUID"


class TestAssetCreation:
    def test_conditional_nameplate_fields_per_equipment_class(self, api):
        """PRD §3.2: "A pump must carry `rated_flow_gpm`, its nameplate rated flow in gallons per minute, and that field must be omitted or null on the other two classes."
        PRD §3.2: "A safety-relief valve must carry `set_pressure_psig`, its nameplate set pressure, which likewise must be omitted or null for pumps and general valves. A missing or misplaced conditional nameplate field is rejected with `ERR_VALIDATION`."
        PRD §3.2: "The `test_standard` is either `API_610_PER_POINT` or `SHOP_WEIGHTED_AVG`, defaulting to `SHOP_WEIGHTED_AVG` when intake leaves it unspecified."

        Design: Corner/entities/asset_conditional_nameplate_fields
        """
        customer = create_customer(name="Borealis", account_number="BO-110",
                                   credit_limit_cents=500000, warranty_terms_days=365)

        srv_missing = api.create_asset(
            create_asset_payload(customer["id"], serial_number="SRV-X",
                                 equipment_class="SAFETY_RELIEF_VALVE",
                                 manufacturer="Consolidated", model="1900",
                                 set_pressure_psig=None),
            IC,
        )
        # set_pressure_psig=None serializes as explicit null — that is still a
        # missing conditional field for a safety-relief valve.
        validate_error(srv_missing, ApiErrorId.ERR_VALIDATION)

        pump_with_pressure = api.create_asset(
            {"customer_id": customer["id"], "serial_number": "P-X",
             "equipment_class": "PUMP", "manufacturer": "Flowserve", "model": "M2",
             "set_pressure_psig": 100},
            IC,
        )
        validate_error(pump_with_pressure, ApiErrorId.ERR_VALIDATION)

        ok = api.create_asset(
            create_asset_payload(customer["id"], serial_number="P-Y",
                                 equipment_class="PUMP", rated_flow_gpm=500),
            IC,
        )
        asset = validate_success(ok, 201)
        assert_asset(asset)
        assert asset["test_standard"] == "SHOP_WEIGHTED_AVG", (
            "test_standard defaults to SHOP_WEIGHTED_AVG"
        )

    def test_asset_creation_with_unknown_customer_not_found(self, api):
        """PRD §2.6: "4. **Existence** — path-referenced and body-referenced resources must exist, validated left to right (`ERR_NOT_FOUND`, HTTP 404)."

        Design: Corner/entities/asset_creation_with_unknown_customer_not_found
        """
        resp = api.create_asset(
            create_asset_payload(NON_EXISTENT_UUID, serial_number="V-X"),
            IC,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        data, meta = validate_paginated(
            api.list_assets(SM, params={"customer_id": NON_EXISTENT_UUID}))
        assert data == [] and meta["total_count"] == 0, "no Asset row may be persisted"


class TestRepairOrderCreation:
    def test_computed_fields_from_client_input_are_ignored(self, api):
        """PRD §3.3: "An order opens in `RECEIVED` with `repair_round` at zero and `repair_outcome` at `NONE`."
        PRD §3.3: "An order created without `warranty_parent_ro_id` is ordinary commercial work with `warranty_case` false."
        PRD §2.5: "`version` is an integer that increments by one with every mutation of the resource."

        Design: Corner/entities/repair_order_computed_fields_input_ignored
        """
        customer = create_customer(name="Cimarron", account_number="CI-120",
                                   credit_limit_cents=500000, warranty_terms_days=365)
        asset = create_asset(customer["id"], serial_number="V-1201")
        resp = api.create_repair_order(
            create_repair_order_payload(
                customer["id"], asset["id"], estimated_bay_hours=10,
                status="CLOSED", repair_round=99, warranty_case=True),
            IC,
        )
        ro = validate_success(resp, 201)
        assert_repair_order(ro)
        assert ro["status"] == "RECEIVED", "client-supplied status=CLOSED must be ignored"
        assert ro["repair_round"] == 0, "client-supplied repair_round must be ignored"
        assert ro["warranty_case"] is False, "client-supplied warranty_case must be ignored"
        assert ro["version"] == 1

    def test_invalid_failure_mode_enum_returns_validation(self, api):
        """PRD §3.3: "Intake captures the `asset_id` of the serialized unit in for repair, a `failure_mode` of `SEAL_LEAK`, `BEARING_FAILURE`, `CAVITATION`, `SEAT_LEAKAGE`, `SPRING_DRIFT`, or `OTHER`, a free-text `failure_description`, and an `intake_priority` of `STANDARD` or `SURGE` for turnaround and shutdown surge work."
        PRD §2.6: "2. **Request-body shape** — required fields present, enum values valid, date and datetime formats valid, and the conditional nameplate fields present per equipment class (`ERR_VALIDATION`, HTTP 400)."

        Design: Corner/entities/repair_order_invalid_enum_returns_validation
        """
        customer = create_customer(name="Dakota Plains", account_number="DP-130",
                                   credit_limit_cents=500000, warranty_terms_days=365)
        asset = create_asset(customer["id"], serial_number="V-1301")
        resp = api.create_repair_order(
            create_repair_order_payload(customer["id"], asset["id"], failure_mode="BROKEN"),
            IC,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_get_repair_order_not_found_returns_404(self, api):
        """PRD §2.6: "4. **Existence** — path-referenced and body-referenced resources must exist, validated left to right (`ERR_NOT_FOUND`, HTTP 404)."

        Design: Corner/entities/get_repair_order_not_found_returns_404
        """
        resp = api.get_repair_order(NON_EXISTENT_UUID, SM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_repair_order_list_pagination_interaction(self, api):
        """PRD §2.3: "`limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0."
        PRD §2.3: "The repair order list filters by `customer_id`, `asset_id`, `status`, `capacity_window_id`, or `warranty_parent_ro_id`."

        Design: Corner/entities/repair_order_list_pagination_interaction
        """
        customer = create_customer(name="Estrella", account_number="ES-140",
                                   credit_limit_cents=500000, warranty_terms_days=365)
        for serial in ("V-1401", "V-1402", "V-1403"):
            asset = create_asset(customer["id"], serial_number=serial)
            create_repair_order(customer["id"], asset["id"], estimated_bay_hours=5)

        page1, meta1 = validate_paginated(api.list_repair_orders(
            SM, params={"customer_id": customer["id"], "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_repair_orders(
            SM, params={"customer_id": customer["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
