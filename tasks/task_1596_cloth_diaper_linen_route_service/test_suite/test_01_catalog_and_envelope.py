"""Catalog creation defaults, request-format guards, pagination envelope, and
the common system-managed fields every resource carries."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_customer,
    assert_plan,
    assert_pool,
    assert_subscription,
    assert_zone,
    create_customer,
    create_customer_payload,
    create_plan,
    create_subscription,
    create_zone,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as _client
from test_helpers.fixtures import ADMIN, fund_pool, set_clock


class TestCatalogDefaults:
    def test_plan_defaults_applied_on_create(self, api):
        """PRD 3.1: "`overage_cap_items`, the maximum billable overage items per
        week, defaulting to 20 when omitted; `deposit_cents`, the refundable deposit
        automatically charged when a subscription is created; `service_bags_per_week`,
        the number of clean bags exchanged weekly, defaulting to 1; and
        `kit_reserve_pct`, the starter-kit reserve percentage over the weekly quota,
        defaulting to 10 and bounded between 0 and 100."

        Design: Corner/entities/plan_defaults_applied_on_create
        """
        minimal_payload = {
            "tier_code": "MINIMAL",
            "weekly_quota": 50,
            "weekly_fee_cents": 2500,
            "overage_rate_cents": 5,
            "deposit_cents": 10000,
            "weight_policy": "COUNT_BASIS",
        }
        plan = validate_success(_client.create_plan(minimal_payload, ADMIN), 201)
        assert_plan(plan)
        assert plan["overage_cap_items"] == 20, (
            f"overage_cap_items default should be 20, got {plan['overage_cap_items']}"
        )
        assert plan["service_bags_per_week"] == 1, (
            f"service_bags_per_week default should be 1, got {plan['service_bags_per_week']}"
        )
        assert plan["kit_reserve_pct"] == 10, (
            f"kit_reserve_pct default should be 10, got {plan['kit_reserve_pct']}"
        )

        reread = validate_success(_client.get_plan(plan["id"], ADMIN))
        assert reread["overage_cap_items"] == 20
        assert reread["service_bags_per_week"] == 1
        assert reread["kit_reserve_pct"] == 10

    def test_zone_service_days_per_week_computed(self, api):
        """PRD 3.1: "The derived `service_days_per_week` is simply the count of those
        entries and later drives pause-credit proration."

        Design: Corner/entities/zone_service_days_per_week_computed
        """
        response = _client.create_zone(
            {
                "zone_code": "Z-TRI",
                "service_weekdays": ["MON", "WED", "FRI"],
                "stop_cutoff_hours": 24,
                "active": True,
            },
            ADMIN,
        )
        zone = validate_success(response, 201)
        assert_zone(zone)
        assert zone["service_days_per_week"] == 3, (
            f"three weekdays should derive service_days_per_week 3, got "
            f"{zone['service_days_per_week']}"
        )
        reread = validate_success(_client.get_zone(zone["id"], ADMIN))
        assert reread["service_days_per_week"] == 3

    def test_create_pool_invalid_enum_rejected(self, api):
        """PRD 3.1: "A `PlatformAdmin` creates one pool per `size_code` — one of
        `NEWBORN`, `SMALL`, `MEDIUM`, `LARGE`, `XL`, unique across pools — with every
        bucket starting at zero."
        PRD 2.10: "Request format — the body is valid, every required field is
        present with the correct type, enum fields hold a declared member, window
        bounds are ordered (`window_start_minutes` before `window_end_minutes`), scale
        weights are positive, and item counts are at least one. Violations are
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/create_pool_invalid_enum_rejected
        """
        create_zone()
        response = _client.create_pool({"size_code": "JUMBO"}, ADMIN)
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_plan_list_pagination_envelope(self, api):
        """PRD 2.3: "`limit` sets the maximum number of items returned; it defaults to
        10, with a minimum of 1 and a maximum of 100."
        PRD 2.3: "The `meta` object of a list response carries four pagination fields:
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/plan_list_pagination_envelope
        """
        create_plan(tier_code="P1", weight_policy="COUNT_BASIS")
        create_plan(tier_code="P2", weight_policy="WEIGHT_BASIS")

        response = _client.list_plans(ADMIN, params={"limit": 1, "offset": 0})
        data, meta = validate_paginated(response)
        assert len(data) == 1, f"limit=1 should return exactly 1 row, got {len(data)}"
        assert meta["total_count"] == 2, f"total_count should be 2, got {meta['total_count']}"
        assert meta["has_more"] is True, "has_more should be true with one row withheld"
        assert meta["limit"] == 1 and meta["offset"] == 0

    def test_retire_beyond_on_hand_returns_shortfall(self, api):
        """PRD 3.1: "a `RETIRE` adjustment moves units from `on_hand_units` to
        `retired_units` and is refused with `ERR_INVENTORY_SHORTFALL` when on-hand
        stock is below the requested units."

        Design: Corner/validations/retire_beyond_on_hand_returns_shortfall
        """
        pool = fund_pool("XL", 10)
        response = _client.pool_adjustment(
            pool["id"], {"adjustment_type": "RETIRE", "units": 20}, ADMIN
        )
        validate_error(response, ApiErrorId.ERR_INVENTORY_SHORTFALL.value)

        after = validate_success(_client.get_pool(pool["id"], ADMIN))
        assert_pool(after)
        assert after["on_hand_units"] == 10, "failed RETIRE must not move on-hand stock"
        assert after["retired_units"] == 0, "failed RETIRE must not move retired stock"


class TestCustomerCreation:
    def test_create_customer_missing_required_email_returns_400(self, api):
        """PRD 3.2: "A `PlatformAdmin` registers a household by creating a customer
        with `full_name`, a unique `email`, the home `service_zone_id`, the
        `child_birthdate`, and the `child_size_code` (one of `NEWBORN`, `SMALL`,
        `MEDIUM`, `LARGE`, `XL`)."
        PRD 2.10: "Request format — the body is valid, every required field is
        present with the correct type, enum fields hold a declared member, window
        bounds are ordered (`window_start_minutes` before `window_end_minutes`), scale
        weights are positive, and item counts are at least one. Violations are
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/create_customer_missing_required_email_returns_400
        """
        zone = create_zone()
        payload = create_customer_payload(zone["id"])
        del payload["email"]
        response = _client.create_customer(payload, ADMIN)
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_get_customer_not_found_returns_404(self, api):
        """PRD 2.10: "Path existence — every identifier in the URL path exists,
        validated left to right, else `ERR_NOT_FOUND` (404). On a nested path the
        first missing identifier, reading left to right, is the one reported."

        Design: Corner/entities/get_customer_not_found_returns_404
        """
        zone = create_zone()
        create_customer(zone["id"])  # the miss is by id, not by empty collection
        response = _client.get_customer(NON_EXISTENT_UUID, ADMIN)
        validate_error(response, ApiErrorId.ERR_NOT_FOUND.value)

    def test_create_customer_computed_deposit_input_ignored(self, api):
        """PRD 3.2: "New customers land in `ONBOARDING` status with a zeroed deposit
        ledger."

        Design: Corner/entities/create_customer_computed_deposit_input_ignored
        """
        zone = create_zone()
        payload = create_customer_payload(zone["id"])
        payload["deposit_held_cents"] = 99999  # not a declared input; must not stick
        customer = validate_success(_client.create_customer(payload, ADMIN), 201)
        assert_customer(customer)
        assert customer["deposit_held_cents"] == 0, (
            f"client-supplied deposit_held_cents must be ignored; ledger starts at 0, "
            f"got {customer['deposit_held_cents']}"
        )
        assert customer["deposit_charged_cents"] == 0
        assert customer["deposit_applied_cents"] == 0
        assert customer["deposit_refunded_cents"] == 0


class TestCommonFields:
    def test_get_subscription_returns_common_fields(self, api):
        """PRD 2.4: "Every resource in this API — plans, zones, customers,
        subscriptions, pauses, kits, pools, swaps, routes, stops, intakes, formulas,
        batches, cases, and invoices — carries a standard set of system-managed
        fields"
        PRD 2.2: "The `api_request_id` is a server-generated unique identifier for
        the request that starts with `req_`."

        Design: Corner/endpoints/get_subscription_returns_common_fields
        """
        set_clock()
        plan = create_plan(tier_code="STANDARD")
        zone = create_zone()
        fund_pool("MEDIUM", 500)
        customer = create_customer(zone["id"])
        subscription = create_subscription(customer, plan, zone)

        response = _client.get_subscription(subscription["id"], ADMIN)
        assert response.status_code == 200
        body = response.json()
        assert body["response_type"] == "object", (
            f"a single-resource read must report response_type object, got "
            f"{body['response_type']}"
        )
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")

        data = body["data"]
        assert_subscription(data)
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])
        assert isinstance(data["version"], int)
