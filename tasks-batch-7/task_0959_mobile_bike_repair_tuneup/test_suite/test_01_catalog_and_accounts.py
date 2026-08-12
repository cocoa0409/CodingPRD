"""Catalog & account setup: zones, customers, bikes, parts, subscriptions."""
from test_helpers import (
    ApiErrorId,
    assert_bike,
    assert_customer,
    assert_subscription,
    assert_zone,
    make_bike,
    make_customer,
    make_part,
    make_subscription,
    make_zone,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestZones:
    def test_zone_create_applies_active_default(self, api, admin_headers, dispatcher_headers):
        """PRD §3.1: "Each zone has a display `name`, a `base_callout_fee_cents` —
        the travel fee, in cents and never negative, charged once per non-callback
        job in that zone — and an `active` flag, defaulting to true, that governs
        whether new service requests may target the zone."

        Design: Corner/entities/zone_create_applies_active_default
        """
        created = validate_success(api.create_zone(
            {"name": "Z1", "base_callout_fee_cents": 2500}, admin_headers), 201)
        assert_zone(created)
        assert created["active"] is True, "omitted active flag must default to true on create"

        fetched = validate_success(api.get_zone(created["id"], dispatcher_headers), 200)
        assert fetched["active"] is True, "active default must persist on read-back"


class TestCustomers:
    def test_customer_create_system_fields_initialized(self, api, dispatcher_headers):
        """PRD §3.1: "Every account carries an `account_credit_cents` goodwill
        balance that starts at 0."
        PRD §2.4: "The `id` is a server-minted UUID with no type prefix."

        Design: Corner/entities/customer_create_system_fields_initialized
        """
        created = validate_success(api.create_customer(
            {"name": "Ann", "email": "ann@x.com", "account_kind": "INDIVIDUAL"},
            dispatcher_headers), 201)
        assert_customer(created)
        assert created["account_credit_cents"] == 0, "credit balance must start at 0"

        fetched = validate_success(api.get_customer(created["id"], dispatcher_headers), 200)
        assert fetched["account_credit_cents"] == 0, "credit balance must read back as 0"


class TestBikes:
    def test_create_ebike_missing_battery_wh_returns_invalid_request(self, api, dispatcher_headers):
        """PRD §3.1: "For an e-bike, `battery_wh` (capacity in watt-hours) is
        required; for a mechanical bike it must be null — either violation is a
        body-validation failure under §2.10."
        PRD §2.10: "the body must be valid JSON, required fields must be present,
        enum values must lie in their declared sets, and unknown fields are
        rejected, all as `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/create_ebike_missing_battery_wh_returns_invalid_request
        """
        cust = make_customer("INDIVIDUAL")
        resp = api.create_bike({"customer_id": cust["id"], "bike_type": "EBIKE"}, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

        bikes, meta = validate_paginated(api.list_customer_bikes(cust["id"], dispatcher_headers))
        assert bikes == [], f"rejected bike must not persist, got {bikes}"

    def test_create_bike_invalid_enum_returns_invalid_request(self, api, dispatcher_headers):
        """PRD §3.1: "A bike record holds a `bike_type` of `MECHANICAL` or `EBIKE`"
        PRD §2.10: "enum values must lie in their declared sets, and unknown
        fields are rejected, all as `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/create_bike_invalid_enum_returns_invalid_request
        """
        cust = make_customer("INDIVIDUAL")
        resp = api.create_bike(
            {"customer_id": cust["id"], "bike_type": "TRIKE"}, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestNotFound:
    def test_get_request_not_found_returns_404(self, api, dispatcher_headers):
        """PRD §2.8: "The first identifier that does not correspond to an existing
        resource produces an `ERR_NOT_FOUND` (HTTP 404) rejection, and no later
        segment is consulted."

        Design: Corner/entities/get_request_not_found_returns_404
        """
        resp = api.get_service_request(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestUniqueness:
    def test_duplicate_part_sku_rejected(self, api, admin_headers):
        """PRD §3.2: "The parts catalog, likewise administered by a `PlatformAdmin`,
        gives each part a `sku` unique across all parts (`ERR_DUPLICATE_SKU`,
        HTTP 409, on collision)"

        Design: Corner/errors/duplicate_part_sku_rejected
        """
        make_part(sku="A1", name="Chain", unit_price_cents=1200, warranty_days=90)
        resp = api.create_part(
            {"sku": "A1", "name": "Chainring", "unit_price_cents": 3000, "warranty_days": 60},
            admin_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SKU)

    def test_duplicate_customer_email_rejected(self, api, dispatcher_headers):
        """PRD §3.1: "a contact `email` that must be unique across all customers
        (a duplicate is refused with `ERR_EMAIL_EXISTS`, HTTP 409)"

        Design: Corner/errors/duplicate_customer_email_rejected
        """
        make_customer("INDIVIDUAL", email="ann@x.com")
        resp = api.create_customer(
            {"name": "Ann Two", "email": "ann@x.com", "account_kind": "FLEET"},
            dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_EMAIL_EXISTS)


class TestSubscriptions:
    def test_individual_subscription_rejected(self, api, dispatcher_headers):
        """PRD §3.5: "Only `FLEET` and `APARTMENT` accounts qualify — an attempt
        for an `INDIVIDUAL` customer is refused with
        `ERR_SUBSCRIPTION_REQUIRES_ORG_ACCOUNT` (HTTP 422)"

        Design: Corner/validations/individual_subscription_rejected
        """
        cust = make_customer("INDIVIDUAL")
        resp = api.create_subscription({
            "customer_id": cust["id"], "included_tunes_per_period": 4,
            "discount_pct": 0.10,
            "period_start": "2026-05-01T00:00:00Z", "period_end": "2026-05-31T23:59:59Z",
        }, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_REQUIRES_ORG_ACCOUNT)

    def test_duplicate_active_subscription_rejected(self, api, dispatcher_headers):
        """PRD §3.5: "a customer may hold at most one non-`CANCELLED` subscription,
        a second live one drawing `ERR_SUBSCRIPTION_ACTIVE_EXISTS` (HTTP 409)."

        Design: Corner/validations/duplicate_active_subscription_rejected
        """
        cust = make_customer("FLEET")
        make_subscription(cust["id"], included_tunes_per_period=4, discount_pct=0.10)
        resp = api.create_subscription({
            "customer_id": cust["id"], "included_tunes_per_period": 8,
            "discount_pct": 0.20,
            "period_start": "2026-05-01T00:00:00Z", "period_end": "2026-05-31T23:59:59Z",
        }, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_ACTIVE_EXISTS)
