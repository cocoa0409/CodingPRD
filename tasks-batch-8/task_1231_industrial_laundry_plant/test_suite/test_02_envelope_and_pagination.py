"""Response envelope, pagination envelope, and non-persisting computed reads."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
    create_plant, create_customer,
)

ADMIN = TEST_USERS["plant_admin_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


class TestPaginationEnvelope:
    def test_list_customers_pagination_envelope(self, api):
        """PRD §2.3: "All list endpoints accept the query parameters `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` parameter defaults to 0. List responses are always sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.2: "The `data` field contains the resource object or an array of resource objects."

        Design: Corner/endpoints/list_customers_pagination_envelope
        """
        plant = create_plant()
        create_customer(plant["id"], **{"name": "C1", "credit_limit_cents": 1000})
        create_customer(
            plant["id"], name="C2", customer_kind="HEALTHCARE",
            billing_mode="RENTAL", credit_limit_cents=1000,
        )
        resp = api.list_customers(
            plant["id"], ADMIN, params={"limit": 1, "offset": 0}
        )
        assert resp.json().get("response_type") == "array", (
            "list endpoints must return response_type=array"
        )
        data, meta = validate_paginated(resp)
        assert len(data) == 1, f"limit=1 must return one row, got {len(data)}"
        assert meta["total_count"] == 2, f"total_count must be 2, got {meta['total_count']}"
        assert meta["has_more"] is True, "has_more must be true with 2 rows and limit 1"
        assert meta["limit"] == 1
        assert meta["offset"] == 0


class TestErrorEnvelope:
    def test_error_envelope_shape(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/endpoints/error_envelope_shape
        """
        resp = api.get_plant(NON_EXISTENT_UUID, ADMIN)
        body = resp.json()
        assert body.get("response_type") == "error"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert isinstance(error_data["message"], str) and error_data["message"].strip()


class TestBillingPreview:
    def test_billing_preview_never_persists(self, api):
        """PRD §3.8: "A billing preview capability lets a `PlantAdmin`, `CustomerServiceRep`, or `BillingClerk` read what an invoice for a period would contain — the same five money fields `linen_charges_cents`, `lost_item_charges_cents`, `utility_surcharge_cents`, `credits_cents`, and `total_due_cents` — without persisting anything."

        Design: Corner/endpoints/billing_preview_never_persists
        """
        plant = create_plant()
        customer = create_customer(plant["id"], billing_mode="COG")
        resp = api.billing_preview(
            customer["id"], CLERK,
            params={
                "billing_period_start": "2026-05-01",
                "billing_period_end": "2026-06-01",
            },
        )
        preview = validate_success(resp, 200)
        for field in (
            "linen_charges_cents", "lost_item_charges_cents",
            "utility_surcharge_cents", "credits_cents", "total_due_cents",
        ):
            assert isinstance(preview.get(field), int), (
                f"preview must carry integer {field}"
            )
        invoices, meta = validate_paginated(api.list_invoices(customer["id"], CLERK))
        assert invoices == [] and meta["total_count"] == 0, (
            "billing-preview must not persist an invoice"
        )
