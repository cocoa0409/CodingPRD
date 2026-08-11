"""Household onboarding, referential existence, RBAC denials, and read-after-write
consistency."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, assert_household, is_valid_uuid,
    create_household, create_coop, create_visit, create_route,
    create_household_payload, create_coop_site_payload,
    make_customer_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_admin_headers"]
TECH = TEST_USERS["service_tech_headers"]


class TestHouseholdOnboarding:
    def test_household_creation_applies_system_defaults(self, api):
        """PRD §3.1: "A new household starts in `ACTIVE` status with a
        `wallet_credit_cents` balance of 0."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."

        Design: Corner/entities/household_creation_defaults
        """
        res = api.create_household(
            create_household_payload(
                name="H Def", address="20 Hen Ln", zone_code="SUBURBAN"),
            ADMIN,
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        household = body["data"]
        assert_household(household)
        assert household["status"] == "ACTIVE", (
            f"New household must start ACTIVE, got {household['status']}")
        assert household["wallet_credit_cents"] == 0, (
            f"New household wallet must be 0, got {household['wallet_credit_cents']}")
        assert is_valid_uuid(household["id"])

    def test_household_missing_zone_code_rejected(self, api):
        """PRD §2.8: "Required fields present, types valid, enum values within
        their declared sets, end strictly after start for visit, stop, and
        invoice windows, well-formed MM-DD and HH:MM strings, positive
        quantities. Failures yield `ERR_INVALID_REQUEST` or
        `ERR_INVALID_TIME_RANGE`."

        Design: Corner/entities/household_missing_required_field_returns_invalid_request
        """
        res = api.create_household(
            {"name": "H Bad", "email": "hbad@test.example", "address": "21 Hen Ln"},
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_household_unknown_zone_rejected(self, api):
        """PRD §3.1: "A `PlatformAdmin` onboards a household by supplying its
        display `name`, a contact `email` that must be unique across all
        households, the service street `address`, and a `zone_code` of `URBAN`,
        `SUBURBAN`, or `RURAL` — the zone drives the visit-pricing multiplier
        described in §3.5."
        PRD §2.8: "Failures yield `ERR_INVALID_REQUEST` or
        `ERR_INVALID_TIME_RANGE`."

        Design: Corner/entities/household_invalid_enum_zone_rejected
        """
        res = api.create_household(
            create_household_payload(
                name="H Enum", address="22 Hen Ln", zone_code="NOWHERE"),
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_coop_site_with_unknown_household_rejected(self, api):
        """PRD §2.9: "A payload naming an unknown subscription plan (via
        `plan_id` on subscription creation or `new_plan_id` on a plan change) is
        rejected with `ERR_PLAN_NOT_FOUND`; an unknown catalog entry via
        `product_sku` yields `ERR_PRODUCT_NOT_FOUND`; an unknown engagement via
        `engagement_id` yields `ERR_ENGAGEMENT_NOT_FOUND`; and likewise for
        household, coop site, and visit references within their respective
        not-found codes."

        Design: Corner/entities/coop_site_create_household_not_found
        """
        res = api.create_coop_site(
            create_coop_site_payload(NON_EXISTENT_UUID, site_label="ghost",
                                     coop_capacity_hens=4),
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_HOUSEHOLD_NOT_FOUND)


class TestImmediateConsistency:
    def test_suspend_immediately_visible_on_read(self, api):
        """PRD §3.1: "When a household stops paying or violates policy, a
        `BillingAdmin` suspends it, moving `status` from `ACTIVE` to
        `SUSPENDED`; suspending a household that is not `ACTIVE` is rejected
        with `ERR_ACCOUNT_SUSPENDED`."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/immediate_read_after_suspend
        """
        household = create_household(name="H Imm", address="59 Hen Ln")
        suspended = validate_success(api.suspend_household(household["id"], BILLING), 200)
        assert suspended["status"] == "SUSPENDED"

        reread = validate_success(api.get_household(household["id"], BILLING), 200)
        assert reread["status"] == "SUSPENDED", (
            "The read immediately following the suspend must show SUSPENDED")


class TestRoleDenials:
    def test_customer_cannot_publish_route(self, api):
        """PRD §2.1: "Furthermore, access to specific operations is restricted
        by role; an attempt to perform an action outside of the caller's
        designated role will be rejected with an `ERR_INSUFFICIENT_PERMISSIONS`
        error (HTTP 403)."
        PRD §4: "| POST | `/coopcare/sitting-routes/{id}/publish` | Publish a
        planned route so the selector can assign stops | Dispatcher |"

        Design: Corner/rbac/customer_cannot_publish_route
        """
        household = create_household(name="H RB1", address="52 Hen Ln")
        route = create_route(route_date="2026-07-10T00:00:00Z")
        res = api.publish_sitting_route(
            route["id"], make_customer_headers(household["id"]))
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        route_after = validate_success(api.get_sitting_route(route["id"], DISPATCHER), 200)
        assert route_after["status"] == "PLANNED"

    def test_service_tech_cannot_generate_invoice(self, api):
        """PRD §2.1: "Furthermore, access to specific operations is restricted
        by role; an attempt to perform an action outside of the caller's
        designated role will be rejected with an `ERR_INSUFFICIENT_PERMISSIONS`
        error (HTTP 403)."
        PRD §4: "| POST | `/coopcare/invoices` | Generate a DRAFT invoice for a
        household and period by sweeping unbilled sources | BillingAdmin |"

        Design: Corner/rbac/servicetech_cannot_generate_invoice
        """
        household = create_household(name="H RB2", address="53 Hen Ln")
        res = api.create_invoice(
            {"household_id": household["id"],
             "period_start": "2026-05-01T00:00:00Z",
             "period_end": "2026-06-01T00:00:00Z"},
            TEST_USERS["service_tech_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_dispatcher_cannot_adjust_wallet(self, api):
        """PRD §2.1: "Furthermore, access to specific operations is restricted
        by role; an attempt to perform an action outside of the caller's
        designated role will be rejected with an `ERR_INSUFFICIENT_PERMISSIONS`
        error (HTTP 403)."
        PRD §4: "| POST | `/coopcare/households/{id}/wallet-adjustments` | Grant
        or claw back wallet credit (signed amount; balance stays non-negative) |
        BillingAdmin |"

        Design: Corner/rbac/dispatcher_cannot_adjust_wallet
        """
        household = create_household(name="H RB3", address="54 Hen Ln")
        res = api.adjust_wallet(
            household["id"], {"amount_cents": 1000, "reason": "attempt"}, DISPATCHER)
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        after = validate_success(api.get_household(household["id"], BILLING), 200)
        assert after["wallet_credit_cents"] == 0


class TestCustomerOwnership:
    def test_customer_cannot_cancel_other_households_visit(self, api):
        """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id`
        of the acting `HouseholdAccount`; ownership checks on any resource that
        references a household compare the resource's `household_id` field to
        `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`
        (HTTP 403)."

        Design: Corner/validations/customer_cannot_cancel_other_households_visit
        """
        household_a = create_household(name="H OwnA", address="41 Hen Ln")
        household_b = create_household(name="H OwnB", address="42 Hen Ln")
        coop = create_coop(household_a, 4)
        visit = create_visit(household_a, coop, "SETUP_INSTALL",
                             "2026-06-10T09:00:00Z", "2026-06-10T11:00:00Z")

        res = api.cancel_visit(visit["id"], make_customer_headers(household_b["id"]))
        validate_error(res, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

        after = validate_success(api.get_service_visit(visit["id"], DISPATCHER), 200)
        assert after["status"] == "REQUESTED"
