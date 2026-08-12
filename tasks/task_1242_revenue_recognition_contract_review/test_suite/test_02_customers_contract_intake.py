"""Customer registration and contract intake (PRD §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_paginated,
    is_valid_uuid,
    create_customer_payload, create_contract_payload,
    create_customer, create_contract, get_contract,
    assert_customer, assert_contract, assert_contract_ledger_identity,
)


class TestCustomerCreation:
    def test_missing_external_ref_returns_invalid_request(self, api, accountant_headers):
        """PRD §3.1: "A `RevenueAccountant` registers a customer by supplying its
        `legal_name` and an `external_ref`".
        PRD §2.8: "At this same tier, required request fields must be present
        — including pattern-conditional fields such as the service dates for a
        straight-line obligation or `estimated_total_cost_cents` for an
        input-cost obligation — values must be well-formed, and enum fields must
        hold declared members; failures of this kind return `ERR_INVALID_REQUEST`
        (HTTP 400)."

        Design: Corner/entities/customer_missing_required_field_returns_invalid_request
        """
        resp = api.create_customer({"legal_name": "No Ref Co"}, accountant_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_missing_legal_name_returns_invalid_request(self, api, accountant_headers):
        """PRD §3.1: "A `RevenueAccountant` registers a customer by supplying its
        `legal_name` and an `external_ref`".
        PRD §2.8: "required request fields must be present ... failures of this
        kind return `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/customer_missing_required_field_returns_invalid_request
        """
        resp = api.create_customer({"external_ref": "ONLY-REF"}, accountant_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_create_customer_success(self, api, accountant_headers):
        """PRD §3.1: "A `RevenueAccountant` registers a customer by supplying its
        `legal_name` and an `external_ref`; the external reference is unique per
        customer".

        Design: Corner/entities/customer_missing_required_field_returns_invalid_request
        """
        resp = api.create_customer(
            create_customer_payload(legal_name="Acme Corp", external_ref="ACME-1"),
            accountant_headers,
        )
        customer = validate_success(resp, 201)
        assert_customer(customer)
        assert customer["legal_name"] == "Acme Corp"
        assert customer["external_ref"] == "ACME-1"


class TestContractCreationDefaults:
    def test_creation_applies_defaults_and_computed_fields(self, api, accountant_headers):
        """PRD §3.1: "An optional `package_negotiated_flag`, defaulting to
        `false`, records that the contract was negotiated as a package with
        other contracts".
        PRD §3.1: "A newly created contract starts in `DRAFT` with its financial
        measures at their origins: `vc_estimate_cents` is zero,
        `transaction_price_cents` equals the fixed consideration, and
        `allocated_total_cents`, `billed_to_date_cents`,
        `recognized_to_date_cents`, `deferred_revenue_balance_cents`, and
        `contract_asset_balance_cents` are all zero."

        Design: Corner/entities/contract_creation_applies_defaults_and_computed_fields
        """
        customer = create_customer(legal_name="Defaults Co", external_ref="DEF-1")
        resp = api.create_contract(
            create_contract_payload(
                customer["id"], contract_ref="C-DEF",
                fixed_consideration_cents=250000, risk_tier="ELEVATED",
            ),
            accountant_headers,
        )
        contract = validate_success(resp, 201)
        assert_contract(contract)
        assert contract["package_negotiated_flag"] is False
        assert contract["status"] == "DRAFT"
        assert contract["vc_estimate_cents"] == 0
        assert contract["transaction_price_cents"] == 250000
        assert contract["allocated_total_cents"] == 0
        assert contract["billed_to_date_cents"] == 0
        assert contract["recognized_to_date_cents"] == 0
        assert contract["deferred_revenue_balance_cents"] == 0
        assert contract["contract_asset_balance_cents"] == 0
        assert contract["version"] == 1
        assert is_valid_uuid(contract["id"])

    def test_creation_null_references_and_ledger_identity(self, api, accountant_headers):
        """PRD §3.1: "The `combined_into_contract_id` and
        `active_vc_estimate_id` references and the `completed_at` timestamp are
        null."
        PRD §2.11: "billings minus recognition always equals deferred revenue
        minus contract asset."

        Design: Corner/entities/contract_creation_applies_defaults_and_computed_fields
        """
        customer = create_customer()
        contract = create_contract(customer["id"], fixed_consideration_cents=100000)
        assert contract["combined_into_contract_id"] is None
        assert contract["active_vc_estimate_id"] is None
        assert contract["completed_at"] is None
        assert_contract_ledger_identity(contract)


class TestContractLookup:
    def test_contract_not_found_returns_404(self, api, accountant_headers):
        """PRD §2.9: "The first identifier that does not resolve to an existing
        resource rejects the request with `ERR_NOT_FOUND` (HTTP 404)".

        Design: Corner/entities/contract_not_found_returns_404
        """
        resp = api.get_contract("00000000-0000-4000-8000-000000000000", accountant_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_get_contract_round_trip(self, api, accountant_headers):
        """PRD §3.1: "Against a registered customer, the accountant opens a
        contract — the central organizing entity of the system — by providing
        the `customer_id`, a `contract_ref` (unique per contract), the
        `signed_date` as an ISO `yyyy-mm-dd` string, the
        `fixed_consideration_cents` (a non-negative integer count of cents), and
        the contract's `risk_tier`, which must be one of `STANDARD`, `ELEVATED`,
        or `HIGH`."

        Design: Corner/entities/contract_not_found_returns_404
        """
        customer = create_customer()
        created = create_contract(
            customer["id"], contract_ref="C-RT", risk_tier="HIGH",
            fixed_consideration_cents=777,
        )
        fetched = get_contract(created["id"])
        assert fetched["id"] == created["id"]
        assert fetched["customer_id"] == customer["id"]
        assert fetched["contract_ref"] == "C-RT"
        assert fetched["risk_tier"] == "HIGH"
        assert fetched["fixed_consideration_cents"] == 777
        assert fetched["signed_date"] == "2026-05-20"
