"""Platform invariants: optimistic concurrency, error envelope shape, list
filters, and the residual state-error catalog."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_candidate_payload,
    create_jurisdiction_rule_payload,
    create_order_payload,
    create_package_payload,
    create_report_payload,
    get_success_data,
    list_orders_filtered,
    make_vendor_agent_headers,
    setup_report_received,
    setup_screening_config,
    validate_error,
    validate_success,
    TEST_USERS,
)

HR = TEST_USERS["hr_admin_headers"]
HM = TEST_USERS["hiring_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]


class TestOptimisticConcurrency:
    def test_occ_package_update_stale_and_fresh(self, api):
        """PRD section "Optimistic Concurrency Control": "Updating a `DRAFT`
        screening package requires the request body to carry
        `expected_package_version`, holding the package `version` the client
        last observed; if the package's current `version` has advanced since
        that observation, the update is rejected with `ERR_STALE_VERSION` (HTTP
        412)" and "A successful OCC-guarded write increments the resource's
        `version` by one."

        Design: Corner/cross_cutting_layers/occ_package_update_stale_and_fresh
        """
        pkg = validate_success(
            api.create_package(create_package_payload(name="P-XC1"), HR),
            expected_status=201,
        )
        observed = pkg["version"]

        updated = validate_success(
            api.update_package(
                pkg["id"], {"fee_cents": 1200,
                            "expected_package_version": observed}, HR
            )
        )
        assert updated["version"] == observed + 1
        assert updated["fee_cents"] == 1200

        # Replaying the stale observed version is rejected.
        resp = api.update_package(
            pkg["id"], {"fee_cents": 1500,
                        "expected_package_version": observed}, HR
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        pkg_now = validate_success(api.get_package(pkg["id"], HR))
        assert pkg_now["fee_cents"] == 1200

        # The fresh version succeeds.
        updated2 = validate_success(
            api.update_package(
                pkg["id"], {"fee_cents": 1300,
                            "expected_package_version": updated["version"]}, HR
            )
        )
        assert updated2["version"] == updated["version"] + 1
        assert updated2["fee_cents"] == 1300

    def test_occ_jurisdiction_rule_patch(self, api):
        """PRD section "Optimistic Concurrency Control": "Patching a `DRAFT`
        jurisdiction rule requires `expected_jurisdiction_rule_version` under
        the same rule: a mismatch against the rule's current `version` is
        rejected with `ERR_STALE_VERSION` (HTTP 412)"."

        Design: Corner/cross_cutting_layers/occ_jurisdiction_rule_patch
        """
        rule = validate_success(
            api.create_jurisdiction_rule(
                create_jurisdiction_rule_payload(jurisdiction_code="US-WA"), CO
            ),
            expected_status=201,
        )
        observed = rule["version"]

        patched = validate_success(
            api.patch_jurisdiction_rule(
                rule["id"],
                {"pre_adverse_wait_business_days": 6,
                 "expected_jurisdiction_rule_version": observed},
                CO,
            )
        )
        assert patched["version"] == observed + 1
        assert patched["pre_adverse_wait_business_days"] == 6

        resp = api.patch_jurisdiction_rule(
            rule["id"],
            {"pre_adverse_wait_business_days": 8,
             "expected_jurisdiction_rule_version": observed},
            CO,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        rule_now = validate_success(api.get_jurisdiction_rule(rule["id"], CO))
        assert rule_now["pre_adverse_wait_business_days"] == 6


class TestErrorEnvelope:
    def test_error_envelope_shape_on_failure(self, api):
        """PRD section "Standard Error Response Format": "The `meta` object for
        error responses contains only `api_request_id` and
        `api_request_timestamp`." and "The `error_id` is a unique,
        machine-readable string that identifies the specific error. The
        `message` provides a human-readable explanation of what went wrong."

        Design: Corner/errors/error_envelope_shape_on_failure
        """
        resp = api.get_vendor(NON_EXISTENT_UUID, HR)
        body = resp.json()
        assert resp.status_code == 404
        assert body["response_type"] == "error"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert (
            isinstance(body["data"]["message"], str)
            and len(body["data"]["message"].strip()) > 0
        )

        # Contrast with a success envelope.
        ok = api.create_vendor(
            {"name": "V-ER2", "base_tat_business_hours": 40,
             "max_concurrent_orders": 5},
            HR,
        )
        ok_body = ok.json()
        assert ok.status_code == 201
        assert ok_body["response_type"] == "object"
        assert isinstance(ok_body["meta"]["api_request_id"], str)
        assert isinstance(ok_body["meta"]["api_request_timestamp"], str)


class TestResidualStateErrors:
    def test_residual_state_error_catalog_triggers(self, api):
        """PRD section "Vendor Lifecycle": "A `ComplianceOfficer` may suspend an
        `ACTIVE` vendor (any other status rejects with `ERR_VENDOR_NOT_ACTIVE`)."
        and PRD section "Report Delivery": "the order's fulfillment must be
        `DISPATCHED`, else `ERR_ORDER_NOT_DISPATCHED`" and PRD section
        "Configuring the Screening Catalog": "activation requires `DRAFT`
        (`ERR_MATRIX_NOT_DRAFT`)" and "Rules are born `DRAFT` and are patched,
        while still draft, through the OCC-guarded patch"."

        Design: Corner/errors/residual_state_error_catalog_triggers
        """
        # Vendor suspended once; a second suspend targets a non-ACTIVE vendor.
        vendor = get_success_data(
            api.create_vendor(
                {"name": "V-ER1", "base_tat_business_hours": 40,
                 "max_concurrent_orders": 5},
                HR,
            )
        )
        get_success_data(api.suspend_vendor(vendor["id"], CO))
        resp1 = api.suspend_vendor(vendor["id"], CO)
        validate_error(resp1, ApiErrorId.ERR_VENDOR_NOT_ACTIVE)

        # An order already REPORT_RECEIVED rejects a second delivery.
        ctx = setup_report_received(
            tag="ER1B", findings=[], deliver_at="2026-08-06T10:00:00Z"
        )
        resp2 = api.create_report(
            create_report_payload(ctx["order"]["id"], findings=[]),
            make_vendor_agent_headers(ctx["vendor"]["id"]),
        )
        validate_error(resp2, ApiErrorId.ERR_ORDER_NOT_DISPATCHED)

        # Activating an already-ACTIVE matrix.
        resp3 = api.activate_matrix(ctx["matrix"]["id"], CO)
        validate_error(resp3, ApiErrorId.ERR_MATRIX_NOT_DRAFT)

        # Patching a rule that has left DRAFT (now ACTIVE), with the current
        # version so the OCC check passes and the state gate fires.
        rule = validate_success(
            api.create_jurisdiction_rule(
                create_jurisdiction_rule_payload(jurisdiction_code="US-WA"), CO
            ),
            expected_status=201,
        )
        get_success_data(api.activate_jurisdiction_rule(rule["id"], CO))
        current = validate_success(api.get_jurisdiction_rule(rule["id"], CO))
        resp4 = api.patch_jurisdiction_rule(
            rule["id"],
            {"lookback_years_limit": 6,
             "expected_jurisdiction_rule_version": current["version"]},
            CO,
        )
        validate_error(resp4, ApiErrorId.ERR_RULE_NOT_DRAFT)


class TestOrderListFilters:
    def test_order_list_filters_combine(self, api):
        """PRD section "Pagination": "Unless otherwise specified, every list
        endpoint returns resources sorted by `created_at` ascending." and PRD
        endpoint table: "GET `/screening-orders` | List orders with filters
        (`candidate_id`, `position_id`, `vendor_id`, `fulfillment_status`,
        `adjudication_status`, `rescreen_of_order_id`, `pinned_package_id`,
        `pinned_matrix_id`)"."

        Design: Corner/endpoints/order_list_filters_combine
        """
        ctx = setup_screening_config(tag="EP2", with_matrix=False)
        position2 = get_success_data(
            api.create_position(
                {
                    "title": "T2",
                    "department": "D",
                    "risk_tier": "TIER_1_STANDARD",
                    "package_id": ctx["package"]["id"],
                    "jurisdiction_code": "US-CA",
                    "annual_salary_cents": 9000000,
                },
                HR,
            )
        )
        candidate = get_success_data(
            api.create_candidate(
                create_candidate_payload(full_name="Ep Two", email="ep2@x.com"), HR
            )
        )
        order1 = get_success_data(
            api.create_order(
                create_order_payload(candidate["id"], ctx["position"]["id"]), HM
            )
        )
        order2 = get_success_data(
            api.create_order(
                create_order_payload(candidate["id"], position2["id"]), HM
            )
        )
        get_success_data(api.cancel_order(order1["id"], HM))

        # Combined filter: this candidate's DRAFT orders is exactly order2.
        draft, meta_draft = list_orders_filtered(
            HM, candidate_id=candidate["id"], fulfillment_status="DRAFT"
        )
        assert [o["id"] for o in draft] == [order2["id"]]
        assert meta_draft["total_count"] == 1

        # The cancelled order appears only under the CANCELLED filter.
        cancelled, _ = list_orders_filtered(HM, fulfillment_status="CANCELLED")
        assert [o["id"] for o in cancelled] == [order1["id"]]

        all_mine, meta_all = list_orders_filtered(HM, candidate_id=candidate["id"])
        assert meta_all["total_count"] == 2
