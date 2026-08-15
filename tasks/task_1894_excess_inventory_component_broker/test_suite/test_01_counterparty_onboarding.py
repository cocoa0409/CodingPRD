"""Counterparty onboarding: seller/customer/bin creation defaults and envelope shape."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_seller, create_customer, create_bin,
    create_seller_payload, create_storage_bin_payload,
    make_customer_headers,
    api_client,
    TEST_USERS,
    ApiErrorId,
)

BROKER = TEST_USERS["broker_ops_headers"]
FINANCE = TEST_USERS["finance_admin_headers"]


class TestCustomerDefaults:
    def test_customer_default_urgency_tier_is_standard(self, api):
        """PRD section 3.1: "Customer registration captures a `name`, a
        `contact_email`, a `credit_limit_cents` establishing the maximum
        open-order exposure the broker will extend — it may be zero but never
        negative — and an optional `urgency_tier` of `STANDARD`, `PRIORITY`, or
        `CRITICAL`, defaulting to `STANDARD`, which drives the provisional
        price premium defined in §3.6."

        Design: Corner/entities/customer_default_urgency_tier_applied
        """
        res = api.create_customer(
            {"name": "Default Dan", "contact_email": "dan@x.com",
             "credit_limit_cents": 50000},
            BROKER,
        )
        customer = validate_success(res, 201)
        assert customer["urgency_tier"] == "STANDARD", (
            f"omitted urgency_tier must default to STANDARD, got "
            f"{customer['urgency_tier']!r}"
        )

        fetched = validate_success(api.get_customer(customer["id"], BROKER), 200)
        assert fetched["urgency_tier"] == "STANDARD"

    def test_customer_open_order_exposure_starts_at_zero(self, api):
        """PRD section 3.1: "The customer's `open_order_exposure_cents` starts
        at zero and is maintained by the system as orders open and close."

        Design: Corner/entities/customer_default_urgency_tier_applied
        """
        customer = create_customer(name="Default Dan", credit_limit_cents=50000)
        assert customer["open_order_exposure_cents"] == 0

        fetched = validate_success(api.get_customer(customer["id"], BROKER), 200)
        assert fetched["open_order_exposure_cents"] == 0


class TestSellerCreation:
    def test_seller_computed_balances_open_at_zero(self, api):
        """PRD section 3.1: "Two computed balances track what the broker owes
        the seller over time: `account_balance_cents`, the unpaid consignment
        proceeds currently owed, and `total_payouts_cents`, the lifetime sum of
        seller payouts across every settled order for lots originating from
        that seller. Both open at zero, and §3.7 describes the single event
        that grows them."

        Design: Corner/entities/seller_creation_returns_computed_zero_balances
        """
        res = api.create_seller(
            create_seller_payload(name="Init Ian", contact_email="ian@x.com"),
            BROKER,
        )
        seller = validate_success(res, 201)
        assert seller["account_balance_cents"] == 0
        assert seller["total_payouts_cents"] == 0

        fetched = validate_success(api.get_seller(seller["id"], FINANCE), 200)
        assert fetched["account_balance_cents"] == 0
        assert fetched["total_payouts_cents"] == 0

    def test_seller_payout_terms_days_defaults_to_30(self, api):
        """PRD section 3.1: "`BrokerOps` registers each selling counterparty
        with a legal `name`, a `contact_email`, and optionally
        `payout_terms_days`, the seller's net payment terms in days, which
        defaults to 30 and is informational only — no settlement behavior reads
        it."

        Design: Corner/entities/seller_creation_returns_computed_zero_balances
        """
        seller = create_seller(name="Init Ian")
        assert seller["payout_terms_days"] == 30, (
            f"omitted payout_terms_days must default to 30, got "
            f"{seller['payout_terms_days']!r}"
        )


class TestStorageBinUniqueness:
    def test_duplicate_bin_code_rejected(self, api):
        """PRD section 3.1: "Each bin carries a human-readable `bin_code` that
        must be unique across all bins — a duplicate submission is rejected
        with `ERR_DUPLICATE_BIN_CODE` — and a `capacity_units` greater than
        zero."

        Design: Corner/validations/duplicate_bin_code_rejected
        """
        create_bin(capacity_units=10, bin_code="BIN-DUP")
        res = api.create_storage_bin(
            create_storage_bin_payload(bin_code="BIN-DUP", capacity_units=99),
            BROKER,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_BIN_CODE)


class TestResponseEnvelope:
    def test_list_response_envelope_and_pagination_meta(self, api):
        """PRD section 2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD section 2.3: "The `meta` object of every list response carries the
        four pagination fields `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/endpoints/response_envelope_success_shape
        """
        seller = create_seller(name="Env Eve")
        raw = api.list_seller_buy_offers(seller["id"], BROKER)
        data, meta = validate_paginated(raw)
        body = raw.json()
        assert body["response_type"] == "array"
        assert body["meta"]["api_request_id"]
        assert body["meta"]["api_request_timestamp"]
        assert data == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False
