"""Byproduct sales stock accounting, grower defaults, error envelope, listings."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_byproduct_sale,
    assert_grower,
    create_byproduct_sale_payload,
    create_grower,
    create_grower_payload,
    create_lot,
    create_processed_lot,
    get_lot,
    make_admin_headers,
    make_intake_headers,
    make_operator_headers,
    record_aflatoxin,
    record_moisture_kernel,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestGrowerDefaultsAndRead:
    def test_grower_create_applies_default_premium_rate(self, api):
        """PRD (Master Data): "Registration may also set a `premium_rate_pct`,
        a grade premium expressed as a fraction between 0 and 1 inclusive that
        rewards lots whose edible kernel share clears the premium bar; when
        omitted it defaults to `0.0`." and "Both start at 0 and move only
        through the settlement actions of §3.8."

        Design: Corner/entities/grower_create_applies_default_premium_rate
        """
        resp = api.create_grower(
            create_grower_payload(
                name="Riverbend Orchards", ranch_code="RB-01",
                base_price_cents_per_lb=250,
            ),
            make_admin_headers(),
        )
        data = validate_success(resp, expected_status=201)
        assert_grower(data)
        assert data["premium_rate_pct"] == 0.0
        assert data["payable_outstanding_cents"] == 0
        assert data["lifetime_paid_cents"] == 0

    def test_grower_get_unknown_id_returns_not_found(self, api):
        """PRD (Referential Integrity): "Each resource type has its own
        not-found error, all HTTP 404: ERR_GROWER_NOT_FOUND for grower
        references".

        Design: Corner/entities/grower_get_unknown_id_returns_not_found
        """
        resp = api.get_grower(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", make_admin_headers()
        )
        validate_error(resp, ApiErrorId.ERR_GROWER_NOT_FOUND)


class TestByproductSales:
    def _setup_completed_run_with_byproduct(self, api):
        """One completed run on a 10000-lb lot: hull_out 1500, shell_out 2000."""
        return create_processed_lot(
            gross_weight_lbs=10000, kernel_out_lbs=6000, shell_out_lbs=2000,
            hull_out_lbs=1500, record_grade=False,
            moisture_pct=6.0, kernel_pct=0.65, foreign_material_pct=0.02,
        )

    def test_byproduct_sale_total_and_stock_accounting(self, api):
        """PRD (Byproduct Sales): "The sale's total_cents is the quantity
        multiplied by the price, rounded half-up to whole cents" and "The
        available stock of a form is the sum of the corresponding output ... over
        all completed processing runs plant-wide, minus the summed quantity_lbs
        of every byproduct sale of that form ever recorded."

        Design: Corner/calculations/byproduct_stock_accounting_and_exhaustion
        """
        self._setup_completed_run_with_byproduct(api)
        resp = api.create_byproduct_sale(
            create_byproduct_sale_payload(
                product_form="HULL", quantity_lbs=1500, price_cents_per_lb=3,
                buyer_name="DairyFeed Co",
            ),
            make_operator_headers(),
        )
        sale = validate_success(resp, expected_status=201)
        assert_byproduct_sale(sale)
        assert sale["total_cents"] == 4500

        # Pool drained: even 1 lb more is overselling.
        resp2 = api.create_byproduct_sale(
            create_byproduct_sale_payload(
                product_form="HULL", quantity_lbs=1, price_cents_per_lb=3,
                buyer_name="DairyFeed Co",
            ),
            make_operator_headers(),
        )
        validate_error(resp2, ApiErrorId.ERR_BYPRODUCT_STOCK_EXCEEDED)

    def test_byproduct_stock_tracked_per_form(self, api):
        """PRD (Byproduct Sales): "Stock accounting is a simple running
        reconciliation per form." Exhausting HULL leaves SHELL stock intact —
        "A sale is allowed only when its quantity_lbs does not exceed the
        available stock of its form at that moment; overselling is rejected with
        ERR_BYPRODUCT_STOCK_EXCEEDED."

        Design: Corner/calculations/byproduct_stock_accounting_and_exhaustion
        """
        self._setup_completed_run_with_byproduct(api)
        # Drain HULL (1500 available).
        validate_success(
            api.create_byproduct_sale(
                create_byproduct_sale_payload(
                    product_form="HULL", quantity_lbs=1500, price_cents_per_lb=3,
                ),
                make_operator_headers(),
            ),
            expected_status=201,
        )
        # SHELL pool untouched: full 2000 sale still succeeds.
        resp = api.create_byproduct_sale(
            create_byproduct_sale_payload(
                product_form="SHELL", quantity_lbs=2000, price_cents_per_lb=4,
            ),
            make_operator_headers(),
        )
        sale = validate_success(resp, expected_status=201)
        assert sale["total_cents"] == 8000


class TestErrorEnvelope:
    def test_error_response_envelope_shape_on_not_found(self, api):
        """PRD (Standard Error Response Format): "All error API responses (4xx
        status codes) follow this standard envelope format" with meta carrying
        api_request_id and api_request_timestamp, response_type 'error', and
        data carrying error_id plus "a human-readable explanation" in message.

        Design: Corner/endpoints/error_response_envelope_shape_on_not_found
        """
        resp = api.get_lot(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", make_admin_headers()
        )
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]
        assert body["data"]["error_id"] == "ERR_LOT_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]


class TestListings:
    def test_lots_list_paginates_with_total_count_and_has_more(self, api):
        """PRD (Pagination): "The meta object of every list response carries
        four pagination fields: limit, offset, total_count, and has_more, where
        total_count reports the full size of the filtered result set and
        has_more indicates whether items remain beyond the returned window."

        Design: Corner/entities/lots_list_paginates_with_total_count_and_has_more
        """
        grower = create_grower()
        create_lot(grower["id"], gross_weight_lbs=1000)
        create_lot(grower["id"], variety="Butte", gross_weight_lbs=2000)
        create_lot(grower["id"], variety="Carmel", gross_weight_lbs=3000)

        data1, meta1 = validate_paginated(
            api.list_lots(make_intake_headers(), params={"limit": 2, "offset": 0})
        )
        assert len(data1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        data2, meta2 = validate_paginated(
            api.list_lots(make_intake_headers(), params={"limit": 2, "offset": 2})
        )
        assert len(data2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_lots_list_filtered_by_status(self, api):
        """PRD (Field Lot Intake): "Lots may be browsed through the list
        endpoint — filterable by grower_id and by status".

        Design: Corner/endpoints/lots_list_filtered_by_status
        """
        grower = create_grower()
        lot_a = create_lot(grower["id"], gross_weight_lbs=1000)
        record_moisture_kernel(lot_a["id"])
        lot_b = create_lot(grower["id"], variety="Butte", gross_weight_lbs=2000)
        record_moisture_kernel(lot_b["id"])
        record_aflatoxin(lot_b["id"], aflatoxin_ppb=25.0)
        assert get_lot(lot_b["id"])["status"] == "REJECTED"

        data, meta = validate_paginated(
            api.list_lots(make_intake_headers(), params={"status": "REJECTED"})
        )
        assert len(data) == 1
        assert data[0]["id"] == lot_b["id"]
        assert meta["total_count"] == 1
