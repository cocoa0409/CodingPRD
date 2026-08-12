"""List endpoints: pagination envelope and status filtering."""
import pytest
from test_helpers import (
    api_client, validate_paginated,
    setup_customer, setup_zone, create_customer_payload, create_draft_invoice,
    OPS_ADMIN, BILLING_ADMIN,
)
from test_helpers import get_success_data


class TestCustomerPagination:
    def test_customers_list_pagination(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned:
        it defaults to 10 when omitted, must be at least 1, and may not exceed
        100. The `offset` parameter skips that many items from the start of the
        result set and defaults to 0. Unless stated otherwise, every list
        endpoint returns resources sorted by `created_at` in ascending order.
        List responses carry `limit`, `offset`, `total_count`, and `has_more` in
        the `meta` object of the envelope."
        PRD §3.2: "Customer listings support filtering by `account_status` and
        `delivery_zone_id` alongside the standard pagination parameters."

        Design: Corner/endpoints/customers_list_pagination
        """
        zone = setup_zone()
        for i in range(3):
            get_success_data(api_client.create_customer(
                create_customer_payload(zone["id"], account_type="HOME",
                                        business_name=f"Pg{i+1}",
                                        billing_email=f"p{i+1}@x.example",
                                        service_address=f"{i+1} P{i+1}"),
                OPS_ADMIN))

        data, meta = validate_paginated(
            api.list_customers(OPS_ADMIN, params={"limit": 2, "offset": 0}))
        assert len(data) == 2, f"limit=2 must return 2 items, got {len(data)}"
        assert meta["total_count"] == 3, f"total_count must be 3, got {meta['total_count']}"
        assert meta["has_more"] is True, "with 3 items and limit 2, has_more must be true"
        assert meta["limit"] == 2
        assert meta["offset"] == 0


class TestInvoiceFiltering:
    def test_invoices_filter_by_status(self, api):
        """PRD §3.8: "Invoice listings may be filtered by `customer_id` and
        `invoice_status`, and each invoice exposes the list of payments recorded
        against it."
        PRD §3.8: "An invoice is drafted for a customer with a
        `billing_period_start`, a `billing_period_end`, and a `due_date`."
        PRD §2.5: "The `version` field is an integer starting at 1 that
        increments by one on every modification to the resource, including
        modifications caused by cascading side effects from operations on other
        resources."

        Design: Corner/endpoints/invoices_filter_by_status
        """
        world = setup_customer(account_type="HOME", business_name="FiltCo",
                               billing_email="f@x.example", service_address="1 F")
        draft = create_draft_invoice(world["customer"]["id"], "2026-04-01",
                                     "2026-05-01", "2026-05-15")
        assert draft["invoice_status"] == "DRAFT"

        data, meta = validate_paginated(
            api.list_invoices(BILLING_ADMIN, params={"invoice_status": "DRAFT"}))
        assert len(data) >= 1, "the drafted invoice must appear in the DRAFT listing"
        for inv in data:
            assert inv["invoice_status"] == "DRAFT", (
                f"filter invoice_status=DRAFT must return only DRAFT invoices, "
                f"got {inv['invoice_status']}"
            )
        assert any(inv["id"] == draft["id"] for inv in data)
