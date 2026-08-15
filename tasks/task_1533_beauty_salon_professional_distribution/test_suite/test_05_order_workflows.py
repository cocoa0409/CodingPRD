"""Order lifecycle: parallel fulfillment/payment dimensions, submission
checks, cancellation lockdown, rejection compensation, item listing, OCC."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    approve_order,
    create_active_salon,
    create_delivered_order,
    create_draft_order,
    get_order,
    list_order_line_items,
    make_brand,
    make_product,
    make_salon_buyer_headers,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestParallelPaymentDimensions:
    def test_submit_then_approve_lands_approved_and_captured(self, api):
        """PRD §3.6: "Approval, by a `DistributionAdmin`, requires the order
        to be `SUBMITTED` (`ERR_INVALID_ORDER_STATE`) and the salon still
        `ACTIVE` (`ERR_ACCOUNT_NOT_ACTIVE`); on success payment moves
        `AUTHORIZED` → `CAPTURED`."

        Design: Difficulty/non_linear_state_machine/order_payment_fulfillment_parallel_dimensions
        """
        salon, _ = create_active_salon()
        brand = make_brand()
        product = make_product(brand["id"], base_price_cents=5000,
                               weight_grams=150)
        order = create_draft_order(
            salon["id"], [{"product_id": product["id"], "quantity": 2}])
        submit_order(order["id"], salon["id"])
        approved = approve_order(order["id"])
        assert approved["fulfillment_status"] == "APPROVED"
        assert approved["payment_status"] == "CAPTURED"
        assert approved["grand_total_cents"] == 10000, (
            "SILVER pricing, no shipping yet: grand == merchandise total")

    def test_submit_then_cancel_lands_cancelled_and_voided(self, api):
        """PRD §3.6: "Cancelling from `SUBMITTED` additionally voids the
        authorization — payment `AUTHORIZED` → `VOIDED` — and reverses the
        provisional accrual."

        Design: Difficulty/non_linear_state_machine/order_payment_fulfillment_parallel_dimensions
        """
        salon, _ = create_active_salon()
        brand = make_brand()
        product = make_product(brand["id"], base_price_cents=5000,
                               weight_grams=150)
        order = create_draft_order(
            salon["id"], [{"product_id": product["id"], "quantity": 1}])
        submit_order(order["id"], salon["id"])
        cancelled = validate_success(api.cancel_order(
            order["id"], make_salon_buyer_headers(salon["id"])), 200)
        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert cancelled["payment_status"] == "VOIDED", (
            "AUTHORIZED is voided on cancel; the order never reaches CAPTURED")


class TestBackbarQuotaBoundary:
    def _salon_with_delivered_retail(self, api, retail_units=10):
        salon, _ = create_active_salon()
        brand = make_brand()
        retail = make_product(brand["id"], variant_type="RETAIL",
                              base_price_cents=10000, weight_grams=250)
        backbar = make_product(brand["id"], variant_type="BACKBAR",
                               base_price_cents=8000, weight_grams=1000)
        create_delivered_order(
            salon["id"], [{"product_id": retail["id"], "quantity": retail_units}])
        return salon, backbar

    def test_backbar_order_exactly_at_ratio_submits(self, api):
        """PRD §3.6: "The backbar quota must pass: over the trailing 90-day
        window ending at the logical clock, sum the non-promotional `BACKBAR`
        and `RETAIL` units on the salon's `DELIVERED` orders whose
        `delivered_at` falls in the window, add this order's non-promotional
        units of each variant, and require that the projected backbar units be
        at most twice the projected retail units — equality is allowed; a
        violation is `ERR_BACKBAR_QUOTA_EXCEEDED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/backbar_quota_exactly_at_ratio_allowed
        """
        salon, backbar = self._salon_with_delivered_retail(api, retail_units=10)
        order = create_draft_order(
            salon["id"], [{"product_id": backbar["id"], "quantity": 20}])
        submitted = validate_success(api.submit_order(
            order["id"], make_salon_buyer_headers(salon["id"])), 200)
        assert submitted["fulfillment_status"] == "SUBMITTED", (
            "20 backbar projected vs 10 retail projected: 20 <= 2.0*10 holds")

    def test_backbar_order_one_over_ratio_rejected(self, api):
        """PRD §3.6: "The backbar quota must pass: over the trailing 90-day
        window ending at the logical clock, sum the non-promotional `BACKBAR`
        and `RETAIL` units on the salon's `DELIVERED` orders whose
        `delivered_at` falls in the window, add this order's non-promotional
        units of each variant, and require that the projected backbar units be
        at most twice the projected retail units — equality is allowed; a
        violation is `ERR_BACKBAR_QUOTA_EXCEEDED` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/backbar_quota_exactly_at_ratio_allowed
        """
        salon, backbar = self._salon_with_delivered_retail(api, retail_units=10)
        order = create_draft_order(
            salon["id"], [{"product_id": backbar["id"], "quantity": 21}])
        resp = api.submit_order(
            order["id"], make_salon_buyer_headers(salon["id"]))
        validate_error(resp, ApiErrorId.ERR_BACKBAR_QUOTA_EXCEEDED)
        assert get_order(order["id"])["fulfillment_status"] == "DRAFT", (
            "a rejected submit leaves the order in DRAFT")


class TestSubmissionConsistency:
    def test_submit_response_reflects_state_immediately(self, api):
        """PRD §2.10: "All writes take effect immediately and atomically: a
        response that reports success reflects every side effect the operation
        carries — cascaded state changes, ledger postings, counter
        recomputations, version increments — with no eventual-consistency
        window."
        PRD §3.6: "On success, payment moves `UNPAID` → `AUTHORIZED`,
        `submitted_at` is stamped with the logical clock, a provisional
        education-credit accrual posts per §3.9, and the order's `version`
        increments by 1."

        Design: Corner/consistency_model/submit_response_reflects_state_immediately
        """
        salon, _ = create_active_salon()
        brand = make_brand()
        product = make_product(brand["id"], base_price_cents=10000)
        order = create_draft_order(
            salon["id"], [{"product_id": product["id"], "quantity": 1}])
        assert order["version"] == 1

        submitted = validate_success(api.submit_order(
            order["id"], make_salon_buyer_headers(salon["id"])), 200)
        assert submitted["fulfillment_status"] == "SUBMITTED"
        assert submitted["payment_status"] == "AUTHORIZED"
        assert submitted["version"] == 2
        assert submitted["submitted_at"] is not None
        assert submitted["submitted_at"].startswith("2026-08-01T00:00:00"), (
            "submitted_at is stamped with the logical clock, which starts at "
            "exactly 2026-08-01T00:00:00Z (PRD §2.4)")

        reread = get_order(order["id"])
        assert reread["fulfillment_status"] == submitted["fulfillment_status"]
        assert reread["payment_status"] == submitted["payment_status"]
        assert reread["version"] == submitted["version"]
        assert reread["submitted_at"] == submitted["submitted_at"]


class TestCancelAndRejectCompensation:
    def test_order_cancel_terminal_lockdown(self, api):
        """PRD §3.6: "Buyer cancellation is available while the order is
        `DRAFT` or `SUBMITTED` (`ERR_INVALID_ORDER_STATE` from any other state
        — in particular, a buyer cannot cancel an `APPROVED` order)."

        Design: Corner/state_machines/order_cancel_terminal_lockdown
        """
        salon, _ = create_active_salon()
        brand = make_brand()
        product = make_product(brand["id"], base_price_cents=3000)
        order = create_draft_order(
            salon["id"], [{"product_id": product["id"], "quantity": 1}])
        validate_success(api.cancel_order(
            order["id"], make_salon_buyer_headers(salon["id"])), 200)

        resp = api.cancel_order(
            order["id"], make_salon_buyer_headers(salon["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_ORDER_STATE)
        assert get_order(order["id"])["fulfillment_status"] == "CANCELLED"

    def test_order_reject_reverses_provisional_and_payment(self, api):
        """PRD §3.6: "Rejection, also by a `DistributionAdmin` and carrying a
        free-text `reason`, requires `SUBMITTED`; on success payment moves
        `AUTHORIZED` → `VOIDED`, the order lands in `REJECTED`, and three
        compensations fire: any `APPLIED` promotion redemption on the order is
        reversed with reason `ORDER_REJECTED` and the promotion's
        `remaining_budget_units` is restored by the redemption's
        `units_consumed`; the `REDEMPTION` credit entry is reversed by a
        `REVERSAL` entry that unwinds `consumed_points` on the same accrual
        entries; and the provisional accrual is reversed by a `REVERSAL`
        entry."

        Design: Corner/state_machines/order_reject_reverses_provisional_and_payment
        """
        salon, _ = create_active_salon()
        brand = make_brand()
        product = make_product(brand["id"], base_price_cents=10000)
        order = create_draft_order(
            salon["id"], [{"product_id": product["id"], "quantity": 1}])
        submit_order(order["id"], salon["id"])
        assert validate_success(
            api.get_salon_account(salon["id"], ADMIN), 200
        )["education_credit_points"] == 10

        rejected = validate_success(api.reject_order(
            order["id"], {"reason": "credit hold"}, ADMIN), 200)
        assert rejected["fulfillment_status"] == "REJECTED"
        assert rejected["payment_status"] == "VOIDED"
        salon_after = validate_success(
            api.get_salon_account(salon["id"], ADMIN), 200)
        assert salon_after["education_credit_points"] == 0, (
            "the provisional accrual is reversed by a REVERSAL entry")


class TestOrderItemsListingAndOcc:
    def test_order_items_filtered_list_pagination(self, api):
        """PRD §2.3: "List endpoints accept `limit` and `offset` query
        parameters. `limit` defaults to 10, with a minimum of 1 and a maximum
        of 100. `offset` defaults to 0. Results are sorted by `created_at`
        ascending. The `meta` object of list responses carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/order_items_filtered_list_pagination
        """
        salon, _ = create_active_salon()
        brand = make_brand()
        p1 = make_product(brand["id"], base_price_cents=3000)
        p2 = make_product(brand["id"], base_price_cents=2000, weight_grams=50)
        order = create_draft_order(salon["id"], [
            {"product_id": p1["id"], "quantity": 1},
            {"product_id": p2["id"], "quantity": 2},
        ])

        page1, meta1 = validate_paginated(api.list_order_items(
            ADMIN, params={"order_id": order["id"], "limit": 1, "offset": 0}))
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_order_items(
            ADMIN, params={"order_id": order["id"], "limit": 1, "offset": 1}))
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert page1[0]["id"] != page2[0]["id"], (
            "the two pages must return disjoint items")

    def test_add_item_to_nonexistent_order_returns_404(self, api):
        """PRD §2.8: "**Existence** — path- and body-referenced resource ids
        exist, validated left-to-right along the path, yielding the
        resource-specific `ERR_<RESOURCE>_NOT_FOUND` (404)."

        Design: Corner/validations/add_item_to_nonexistent_order_returns_404
        """
        salon, _ = create_active_salon()
        brand = make_brand()
        product = make_product(brand["id"], base_price_cents=3000)
        order = create_draft_order(
            salon["id"], [{"product_id": product["id"], "quantity": 1}])

        resp = api.add_order_item(
            NON_EXISTENT_UUID,
            {"product_id": NON_EXISTENT_UUID, "quantity": 1,
             "expected_order_version": order["version"]},
            make_salon_buyer_headers(salon["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND)

    def test_order_item_add_stale_version_returns_412(self, api):
        """PRD §2.6: "Adding an item to a draft order must carry
        `expected_order_version` matching the order's current `version`. If
        the version has advanced — another item add, a credit or promotion
        redemption — the stale add is rejected with `ERR_STALE_VERSION`
        (HTTP 412), so pricing never applies to a snapshot the caller did not
        see."

        Design: Corner/cross_cutting_complexity_layers/order_item_add_stale_version_returns_412
        """
        salon, _ = create_active_salon()
        brand = make_brand()
        p1 = make_product(brand["id"], base_price_cents=3000)
        p2 = make_product(brand["id"], base_price_cents=2000, weight_grams=50)
        order = create_draft_order(
            salon["id"], [{"product_id": p1["id"], "quantity": 1}])
        observed = order["version"]

        validate_success(api.add_order_item(
            order["id"],
            {"product_id": p2["id"], "quantity": 1,
             "expected_order_version": observed},
            make_salon_buyer_headers(salon["id"])), 201)

        resp = api.add_order_item(
            order["id"],
            {"product_id": p2["id"], "quantity": 1,
             "expected_order_version": observed},
            make_salon_buyer_headers(salon["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert len(list_order_line_items(order["id"])) == 2, (
            "the stale add must not create a third line")
