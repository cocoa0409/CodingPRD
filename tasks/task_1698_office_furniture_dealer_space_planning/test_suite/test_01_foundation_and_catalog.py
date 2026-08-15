"""Foundation: envelope, clock, dealership defaults, customer/catalog basics."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_dealership,
    create_asset_tag_payload,
    create_customer_payload,
    create_dealership_payload,
    create_pricing_contract_payload,
    create_product_series_payload,
    create_space_plan_payload,
    create_typical_payload,
    fixtures as fx,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
    AE,
    ADMIN,
    DESIGNER,
)


class TestDealershipDefaults:
    def test_create_dealership_applies_defaults(self, api):
        """PRD section 3.1: "`after_hours_start_minute`, the minute-of-day (on a
        0-to-1439 scale) at which premium billing begins, defaulting to 1080
        (that is, 18:00); `after_hours_multiplier_bp`, the after-hours labor
        multiplier in basis points, defaulting to 15000 (a one-and-a-half-times
        premium); `turnover_buffer_minutes`, the mandatory turnover buffer
        between two confirmed install events on the same crew, defaulting to 30;
        and `credit_cap_pct`, the maximum percent of an order's
        net-plus-install-fee that may be paid by liquidation credit, defaulting
        to 25."

        Design: Corner/entities/create_dealership_applies_defaults
        """
        resp = api.create_dealership(create_dealership_payload(), ADMIN)
        data = validate_success(resp, 201)
        assert_dealership(data)
        assert data["after_hours_start_minute"] == 1080
        assert data["after_hours_multiplier_bp"] == 15000
        assert data["turnover_buffer_minutes"] == 30
        assert data["credit_cap_pct"] == 25


class TestCustomerBasics:
    def test_create_customer_missing_required_field_rejected(self, api):
        """PRD section 3.2: "An `AccountExecutive` onboards each customer
        organization under a dealership, supplying the `dealership_id`, the
        organization `name`, and an `external_ref` that must be unique within
        that dealership (a collision is rejected with `ERR_DUPLICATE_REFERENCE`)."
        Omitting the required external_ref is a malformed body, rejected with
        ERR_INVALID_REQUEST (HTTP 400 per the section 5 catalogue).

        Design: Corner/entities/create_customer_missing_required_field_rejected
        """
        dealership = validate_success(
            api.create_dealership(create_dealership_payload(), ADMIN), 201
        )
        payload = {"dealership_id": dealership["id"], "name": "Acme Corp"}
        resp = api.create_customer(payload, AE)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_nonexistent_customer_returns_404(self, api):
        """PRD section 2.8: "(3) existence of every path identifier and every
        foreign-key identifier in the body" — a well-formed but absent customer
        id is rejected with ERR_NOT_FOUND (HTTP 404 per the section 5
        catalogue).

        Design: Corner/entities/get_nonexistent_customer_returns_404
        """
        resp = api.get_customer(NON_EXISTENT_UUID, AE)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_customer_list_pagination_envelope(self, api):
        """PRD section 2.3: "The `limit` parameter specifies the maximum number
        of items to return; it defaults to 10 when omitted, has a minimum of 1,
        and a maximum of 100. The `offset` parameter specifies how many items to
        skip and defaults to 0." and "Paginated list responses include the
        following fields in the `meta` object of the response envelope:
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/customer_list_pagination_envelope
        """
        dealership = validate_success(
            api.create_dealership(create_dealership_payload(), ADMIN), 201
        )
        for i in range(3):
            validate_success(
                api.create_customer(
                    create_customer_payload(
                        dealership["id"], name=f"C{i+1}", external_ref=f"R{i+1}"
                    ),
                    AE,
                ),
                201,
            )
        page1, meta1 = validate_paginated(
            api.list_customers(
                AE, params={"dealership_id": dealership["id"], "limit": 2, "offset": 0}
            )
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_customers(
                AE, params={"dealership_id": dealership["id"], "limit": 2, "offset": 2}
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_duplicate_customer_external_ref_rejected(self, api):
        """PRD section 3.2: "An `AccountExecutive` onboards each customer
        organization under a dealership, supplying the `dealership_id`, the
        organization `name`, and an `external_ref` that must be unique within
        that dealership (a collision is rejected with `ERR_DUPLICATE_REFERENCE`)."

        Design: Corner/entities/duplicate_customer_external_ref_rejected
        """
        dealership = validate_success(
            api.create_dealership(create_dealership_payload(), ADMIN), 201
        )
        validate_success(
            api.create_customer(create_customer_payload(dealership["id"]), AE), 201
        )
        resp = api.create_customer(
            create_customer_payload(dealership["id"], name="Acme Subsidiary"), AE
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REFERENCE)


class TestCatalog:
    def test_invalid_enum_on_contract_create_rejected(self, api):
        """PRD section 3.3: "An `AccountExecutive` drafts a `PricingContract`
        for a customer, supplying the `customer_id`, a `contract_type` of
        `STATE`, `COOP`, or `NEGOTIATED`, the `pricing_tiers` array, a
        `default_discount_pct`, and the inclusive effectiveness window
        `effective_from` through `effective_to`" — a contract_type of FEDERAL is
        outside that enumeration and is rejected with ERR_INVALID_REQUEST
        (HTTP 400 per the section 5 catalogue).

        Design: Corner/entities/invalid_enum_on_contract_create_rejected
        """
        dealership = validate_success(
            api.create_dealership(create_dealership_payload(), ADMIN), 201
        )
        customer = validate_success(
            api.create_customer(create_customer_payload(dealership["id"]), AE), 201
        )
        payload = create_pricing_contract_payload(customer["id"], contract_type="FEDERAL")
        resp = api.create_pricing_contract(payload, AE)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_duplicate_series_code_rejected(self, api):
        """PRD section 3.1: "Each series is identified by a `series_code` that
        must be unique within the dealership — a duplicate is rejected with
        `ERR_DUPLICATE_REFERENCE`"

        Design: Corner/entities/duplicate_series_code_rejected
        """
        dealership = validate_success(
            api.create_dealership(create_dealership_payload(), ADMIN), 201
        )
        validate_success(
            api.create_product_series(
                create_product_series_payload(dealership["id"]), ADMIN
            ),
            201,
        )
        resp = api.create_product_series(
            create_product_series_payload(
                dealership["id"],
                manufacturer="MILLERKNOLL",
                category="TABLES",
                base_list_price_cents=50_000,
                base_lead_time_days=10,
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_REFERENCE)


class TestSpacePlanComputedFields:
    def test_typical_extended_budget_and_plan_rollup(self, api):
        """PRD section 3.3: "Each typical's `extended_budget_cents` is computed
        as its `quantity` multiplied by its `target_budget_cents_per_instance`,
        and the plan's `budget_cents` is the sum of those extended budgets
        across all its typicals."

        Design: Corner/entities/typical_extended_budget_and_plan_rollup
        """
        dealership = validate_success(
            api.create_dealership(create_dealership_payload(), ADMIN), 201
        )
        customer = validate_success(
            api.create_customer(create_customer_payload(dealership["id"]), AE), 201
        )
        plan = validate_success(
            api.create_space_plan(create_space_plan_payload(customer["id"]), DESIGNER),
            201,
        )
        typical = validate_success(
            api.create_typical(
                create_typical_payload(
                    plan["id"], quantity=4, target_budget_cents_per_instance=250_000
                ),
                DESIGNER,
            ),
            201,
        )
        assert typical["extended_budget_cents"] == 1_000_000
        plan_after = validate_success(api.get_space_plan(plan["id"], DESIGNER))
        assert plan_after["budget_cents"] == 1_000_000


class TestAssetTags:
    def test_asset_tag_initial_status_from_source(self, api):
        """PRD section 3.10: "The initial status depends on the source: a
        `PURCHASED` asset starts `IN_SERVICE`, while a `TRADED_IN` asset starts
        `IN_STORAGE`."

        Design: Corner/entities/asset_tag_initial_status_from_source
        """
        dealership = validate_success(
            api.create_dealership(create_dealership_payload(), ADMIN), 201
        )
        customer = validate_success(
            api.create_customer(create_customer_payload(dealership["id"]), AE), 201
        )
        purchased = validate_success(
            api.create_asset_tag(create_asset_tag_payload(customer["id"]), AE), 201
        )
        traded = validate_success(
            api.create_asset_tag(
                create_asset_tag_payload(
                    customer["id"],
                    description="Used credenza",
                    condition="FAIR",
                    current_location="Warehouse",
                    source="TRADED_IN",
                ),
                AE,
            ),
            201,
        )
        assert purchased["status"] == "IN_SERVICE"
        assert traded["status"] == "IN_STORAGE"


class TestOrderInitialState:
    def test_order_created_with_initial_state(self, api):
        """PRD section 3.4: "Creation requires the customer to be `ACTIVE`
        (`ERR_CUSTOMER_NOT_ACTIVE` otherwise) and produces an order in `DRAFT`
        whose `install_posture` starts at `NOT_SCHEDULED`."
        PRD section 2.4: "`id` (string): a unique, server-minted identifier
        formatted as a UUID with no type prefix." and "`version` (integer): a
        system-managed integer that increments by exactly one on every mutation
        of the resource".

        Design: Corner/entities/order_created_with_initial_state
        """
        ctx = fx.setup_catalog(
            activate=False,
            approve_plan=False,
            contract_overrides={"pricing_tiers": []},
        )
        resp = api.create_project_order(
            {
                "customer_id": ctx.customer["id"],
                "contract_id": ctx.contract["id"],
                "space_plan_id": ctx.plan["id"],
            },
            AE,
        )
        order = validate_success(resp, 201)
        assert order["status"] == "DRAFT"
        assert order["install_posture"] == "NOT_SCHEDULED"
        assert is_valid_uuid(order["id"])
        assert isinstance(order["version"], int)


class TestErrorEnvelope:
    def test_error_envelope_shape(self, api):
        """PRD section 2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`." and "The `error_id` is a
        unique, machine-readable string that identifies the specific error." and
        "The `message` provides a human-readable explanation of what went
        wrong."

        Design: Corner/errors/error_envelope_shape
        """
        resp = api.get_customer(NON_EXISTENT_UUID, AE)
        body = resp.json()
        assert body.get("response_type") == "error"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert err["error_id"] == "ERR_NOT_FOUND"
        assert len(err["message"].strip()) > 0


class TestLogicalClock:
    def test_clock_default_then_set(self, api):
        """PRD section 2.7: "Before any call to set it, the logical clock reads
        exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock time."

        Design: Corner/endpoints/clock_default_then_set
        """
        before = validate_success(api.get_clock(ADMIN))
        assert before["current_utc"] == "2026-08-01T00:00:00Z"
        validate_success(
            api.set_clock({"to_iso8601": "2026-08-15T00:00:00Z"}, ADMIN)
        )
        after = validate_success(api.get_clock(ADMIN))
        assert after["current_utc"] == "2026-08-15T00:00:00Z"
