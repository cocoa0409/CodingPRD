"""Corner (entities) — CRUD, defaults, type constraints, immutability."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    set_clock,
    tick_clock,
    create_default_package,
    register_customer,
    create_pending_contract,
    activate_contract,
    setup_active_contract,
    setup_active_contract_with_item,
    make_customer_headers,
    make_admin_headers,
    assert_contract_package,
    assert_customer,
    create_contract_package_payload,
    create_covered_item_payload,
    create_contract_payload,
)


_ADMIN = make_admin_headers()


class TestContractPackageCreation:

    def test_create_package_with_required_fields_returns_201_and_default_status_active(self, api):
        """PRD §3.1: "The package carries the pricing parameters that drive everything
        downstream: `annual_premium_cents` is the yearly charge applied at activation
        or renewal; `service_fee_cents` is the Trip Charge billed per dispatch;
        `copay_cap_cents` is the per-claim repair-cost cap below which the warranty
        pays the full repair; `copay_share_pct` is the homeowner's share of any repair
        cost above that cap, stored as a decimal between 0 and 1 inclusive;
        `return_visit_window_days` is the size, in days, of the free-return-visit
        guarantee window after a completed dispatch; and `max_covered_items` is the
        ceiling on how many appliances a contract on this package may register."
        PRD §3.1: "A package's lifecycle is governed by its `status`, which begins
        at `ACTIVE` on creation and may be moved to `RETIRED` by a `PlatformAdmin`."
        PRD §2.4: "a `version` integer that begins at 1 on creation"

        Design: Corner/entities/contract_package_creation_minimal_required_fields
        """
        set_clock("2026-01-01T00:00:00Z")
        payload = create_contract_package_payload(
            code="BASIC",
            name="Basic Package",
            annual_premium_cents=30_000,
            service_fee_cents=7_500,
            copay_cap_cents=25_000,
            copay_share_pct=0.20,
            return_visit_window_days=30,
            max_covered_items=3,
        )
        res = api.create_contract_package(payload, _ADMIN)
        body = validate_success(res, 201)
        assert_contract_package(body)
        assert body["status"] == "ACTIVE"
        assert body["version"] == 1
        assert body["code"] == "BASIC"


class TestCustomerRetrieval:

    def test_get_customer_returns_registered_fields(self, api):
        """PRD §3.1: "Registration takes the customer's `email` (which serves as
        their unique login identifier and must be a valid email), `full_name`, and
        `home_address` (the service address technicians will visit)."

        Design: Corner/entities/customer_retrieval_by_id
        """
        customer = register_customer(
            email="alice-retr@example.com",
            full_name="Alice",
            home_address="1 Main St",
        )
        cust_h = make_customer_headers(customer["id"])
        body = validate_success(api.get_customer(customer["id"], cust_h), 200)
        assert_customer(body)
        assert body["email"] == "alice-retr@example.com"
        assert body["full_name"] == "Alice"


class TestContractListingPaginated:

    def test_list_contracts_with_limit_returns_meta_and_data(self, api):
        """PRD §2.3: "All list endpoints accept two query parameters that control
        the page window: `limit`, which sets the maximum number of items in the
        response, and `offset`, which sets the number of leading items to skip."
        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`,
        and `has_more` inside the `meta` object."

        Design: Corner/entities/contract_listing_paginated
        """
        package = create_default_package(code="PLUSPG")
        customer = register_customer(email="page@example.com")
        cust_h = make_customer_headers(customer["id"])
        for _ in range(3):
            get_success_data(api.create_contract(
                create_contract_payload(customer["id"], package["id"]), cust_h
            ))
        res = api.list_contracts(cust_h, params={
            "customer_id": customer["id"], "limit": 2, "offset": 0,
        })
        data, meta = validate_paginated(res)
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True


class TestContractGetNonExistent:

    def test_get_unknown_contract_returns_not_found(self, api):
        """PRD §2.5: "The outermost path identifier is resolved first; if it does
        not point to a row, the request is rejected immediately with `ERR_NOT_FOUND`,
        before any inner identifier or payload field is examined."

        Design: Corner/entities/contract_get_non_existent_returns_not_found
        """
        res = api.get_contract("00000000-0000-4000-8000-000000000000", _ADMIN)
        validate_error(res, "ERR_NOT_FOUND")


class TestContractPackageMissingRequiredField:

    def test_create_package_missing_service_fee_returns_invalid_request(self, api):
        """PRD §3.1: "`service_fee_cents` is the Trip Charge billed per dispatch"
        PRD §2.6: "and finally the request-body shape, type, and bound checks (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/contract_package_create_missing_required_field
        """
        # service_fee_cents is required per PRD §3.1.
        payload = {
            "code": "BAD",
            "name": "Bad",
            "annual_premium_cents": 30_000,
            "copay_cap_cents": 25_000,
            "copay_share_pct": 0.20,
            "return_visit_window_days": 30,
            "max_covered_items": 3,
        }
        res = api.create_contract_package(payload, _ADMIN)
        validate_error(res, "ERR_INVALID_REQUEST")


class TestCoveredItemPreExistingFlagDefault:

    def test_pre_existing_flag_omitted_defaults_to_false(self, api):
        """PRD §3.3: "Registration also accepts an optional `pre_existing_flag`
        which defaults to false if omitted."

        Design: Corner/entities/covered_item_pre_existing_flag_default_false
        """
        package, customer, contract = setup_active_contract()
        cust_h = make_customer_headers(customer["id"])
        # Note: omit pre_existing_flag from payload.
        payload = {
            "contract_id": contract["id"],
            "category": "HVAC",
            "brand": "B",
            "model": "M",
            "install_year": 2022,
        }
        body = validate_success(api.create_covered_item(payload, cust_h), 201)
        assert body["pre_existing_flag"] is False


class TestCoveredItemCategoryEnum:

    def test_create_covered_item_with_invalid_category_returns_invalid_request(self, api):
        """PRD §3.3: "The `category` must be one of the supported enums: `HVAC`,
        `WATER_HEATER`, `REFRIGERATOR`, `DISHWASHER`, `WASHER`, `DRYER`, or `OVEN`."
        PRD §2.6: "and finally the request-body shape, type, and bound checks (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/covered_item_category_enum_validation
        """
        package, customer, contract = setup_active_contract()
        cust_h = make_customer_headers(customer["id"])
        res = api.create_covered_item(
            create_covered_item_payload(contract["id"], category="BLENDER"),
            cust_h,
        )
        validate_error(res, "ERR_INVALID_REQUEST")


class TestContractCreateNonExistentPackage:

    def test_create_contract_with_unknown_package_id_returns_not_found(self, api):
        """PRD §2.5: "The same `ERR_NOT_FOUND` is returned when a foreign-key field
        in a request body — `customer_id`, `package_id`, `contract_id`,
        `covered_item_id`, or `claim_id` — does not resolve to an existing row at
        the moment the request is processed."

        Design: Corner/entities/contract_create_with_nonexistent_package_id
        """
        customer = register_customer()
        cust_h = make_customer_headers(customer["id"])
        res = api.create_contract(
            create_contract_payload(customer["id"], "00000000-0000-4000-8000-000000000000"),
            cust_h,
        )
        validate_error(res, "ERR_NOT_FOUND")


class TestRenewalReminderImmutable:

    def test_renewal_reminder_emitted_on_first_tick_has_correct_days_to_expiry(self, api):
        """PRD §3.8: "The same transition writes a `RenewalReminder` row carrying
        the parent `contract_id`, `sent_utc` equal to the contract's just-stamped
        `renewal_reminder_sent_at`, and `days_to_expiry` equal to the whole number
        of days between the current clock and the contract's `coverage_end_utc`,
        computed by taking the total seconds remaining, dividing by 86400, and
        rounding down to a whole number."

        Design: Corner/entities/renewal_reminder_immutable_no_update_endpoint
        """
        package, customer, contract = setup_active_contract(
            activate_at="2026-01-01T00:00:00Z",
        )
        # Coverage end = 2027-01-01; tick at 2026-12-12 → 20 days remaining.
        set_clock("2026-12-12T00:00:00Z")
        tick_clock()
        cust_h = make_customer_headers(customer["id"])
        res = api.list_renewal_reminders(contract["id"], cust_h)
        data, meta = validate_paginated(res)
        assert len(data) == 1
        rem = data[0]
        assert rem["days_to_expiry"] == 20
