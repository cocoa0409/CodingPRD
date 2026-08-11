"""Customer registration: required fields, defaults, enums, and lookup errors."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, assert_customer,
    create_customer_payload, setup_zone, NON_EXISTENT_UUID,
    OPS_ADMIN,
)


class TestCustomerRegistration:
    def test_customer_creation_with_required_fields_returns_201(self, api):
        """PRD §4: "Operations that create a new resource — a customer, a route,
        a stop on a route, a pricing configuration, a zone, a work order, a cooler
        rental, an add-on, an invoice, or a payment — return `201 Created`."
        PRD §3.2: "New accounts begin `ACTIVE` with `bottles_on_site` at zero."
        PRD §2.5: "The `version` field is an integer starting at 1 that increments
        by one on every modification to the resource, including modifications
        caused by cascading side effects from operations on other resources."

        Design: Corner/entities/customer_creation_with_required_fields_returns_201
        """
        zone = setup_zone()
        payload = create_customer_payload(
            zone["id"], account_type="OFFICE", business_name="NewCo",
            billing_email="n@x.example", service_address="1 N",
            service_mode="AUTO", par_level_bottles=2, pricing_tier="STANDARD",
        )
        res = api.create_customer(payload, OPS_ADMIN)
        customer = validate_success(res, 201)
        assert_customer(customer)
        assert customer["account_status"] == "ACTIVE", \
            f"new account must begin ACTIVE, got {customer['account_status']}"
        assert customer["version"] == 1, f"version must start at 1, got {customer['version']}"
        assert customer["bottles_on_site"] == 0
        assert customer["outstanding_balance_cents"] == 0

    def test_customer_missing_required_field_returns_invalid_request(self, api):
        """PRD §2.6: "Presence, types, and enum membership of required request
        fields — violations return `ERR_INVALID_REQUEST`."
        PRD §3.2: "An `OpsAdmin` registers each customer with an `account_type`
        of `OFFICE` or `HOME`, a `business_name` (the company name for offices,
        a household label for homes), a `billing_email` for invoice delivery, a
        `service_address`, and the `delivery_zone_id` of the zone that will serve
        them; an unresolvable zone reference is rejected with
        `ERR_INVALID_REFERENCE`."

        Design: Corner/entities/customer_missing_required_field_returns_invalid_request
        """
        zone = setup_zone()
        payload = {
            "account_type": "OFFICE",
            "business_name": "BadCo",
            "service_address": "1 B",
            "delivery_zone_id": zone["id"],
        }
        res = api.create_customer(payload, OPS_ADMIN)
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_customer_invalid_enum_account_type(self, api):
        """PRD §2.6: "Presence, types, and enum membership of required request
        fields — violations return `ERR_INVALID_REQUEST`."
        PRD §3.2: "An `OpsAdmin` registers each customer with an `account_type`
        of `OFFICE` or `HOME`, a `business_name` (the company name for offices,
        a household label for homes), a `billing_email` for invoice delivery, a
        `service_address`, and the `delivery_zone_id` of the zone that will serve
        them; an unresolvable zone reference is rejected with
        `ERR_INVALID_REFERENCE`."

        Design: Corner/entities/customer_invalid_enum_account_type
        """
        zone = setup_zone()
        payload = create_customer_payload(
            zone["id"], account_type="BRANCH", business_name="BadEnum",
            billing_email="b@x.example", service_address="1 B",
        )
        res = api.create_customer(payload, OPS_ADMIN)
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_customer_default_pricing_tier_standard(self, api):
        """PRD §3.2: "The `service_mode` is `AUTO` for recurring scheduled
        delivery or `WILL_CALL` for on-demand ordering, defaulting to `AUTO`. The
        `par_level_bottles` is the target bottle inventory an `AUTO` customer
        keeps on site, defaulting to 2 and never negative. A `pricing_tier` of
        `STANDARD`, `SILVER`, or `GOLD` may be assigned at registration and
        defaults to `STANDARD`."

        Design: Corner/entities/customer_default_pricing_tier_standard
        """
        zone = setup_zone()
        payload = {
            "account_type": "HOME",
            "business_name": "DefaultCo",
            "billing_email": "d@x.example",
            "service_address": "1 D",
            "delivery_zone_id": zone["id"],
        }
        res = api.create_customer(payload, OPS_ADMIN)
        customer = validate_success(res, 201)
        assert customer["pricing_tier"] == "STANDARD", \
            f"omitted pricing_tier must default to STANDARD, got {customer['pricing_tier']}"
        assert customer["service_mode"] == "AUTO", \
            f"omitted service_mode must default to AUTO, got {customer['service_mode']}"
        assert customer["par_level_bottles"] == 2, \
            f"omitted par_level_bottles must default to 2, got {customer['par_level_bottles']}"

    def test_customer_get_not_found(self, api):
        """PRD §2.6: "Existence of every resource named by a path parameter —
        violations return `ERR_NOT_FOUND`."

        Design: Corner/entities/customer_get_not_found
        """
        setup_zone()
        res = api.get_customer(NON_EXISTENT_UUID, OPS_ADMIN)
        validate_error(res, "ERR_NOT_FOUND")
