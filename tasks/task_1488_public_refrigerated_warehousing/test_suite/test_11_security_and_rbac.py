"""Authentication, role authorization, ownership reads, and the safety-over-
fiscal validation priority."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_recall,
    create_customer,
    create_customer_with_card,
    create_order,
    create_zone,
    declare_recall,
    get_excursion,
    get_order,
    make_customer_admin_headers,
    receive_stock,
    report_excursion,
    setup_stocked_account,
    validate_error,
    validate_paginated,
    validate_success,
)

OPERATOR = TEST_USERS["warehouse_operator_headers"]
QUALITY = TEST_USERS["quality_manager_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]


class TestAuthentication:
    def test_missing_auth_headers_return_unauthenticated(self, api):
        """PRD §2.1: "Each request must include `X-User-ID` to identify the acting
        user and `X-User-Role` to specify their operational capacity. The system
        recognizes five distinct roles: `CustomerAdmin`, `WarehouseOperator`,
        `QualityManager`, `ClaimsAdjuster`, and `BillingAdmin`. A request that
        arrives without these headers, or carrying a role the system does not
        recognize, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/errors/missing_auth_headers_return_unauthenticated
        """
        # No X-User-Role / X-User-ID headers at all.
        resp = api.list_zones(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRoleAuthorization:
    def test_customer_admin_cannot_manage_zones(self, api):
        """PRD §4: "POST `/api/zones` | Create a temperature zone |
        WarehouseOperator".
        PRD §2.1: "Access to specific operations is restricted by role; an attempt
        to perform an action outside the caller's designated role is rejected with
        `ERR_FORBIDDEN`."

        Design: Corner/rbac/customer_admin_cannot_manage_zones
        """
        customer = create_customer("Rbac Co")
        resp = api.create_zone(
            {"zone_code": "FZ-RB", "temp_class": "FROZEN", "capacity_pallets": 5,
             "dock_doors": 1},
            make_customer_admin_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        _data, meta = validate_paginated(api.list_zones(OPERATOR))
        assert meta["total_count"] == 0, "no zone persisted on rejection"

    def test_warehouse_operator_cannot_confirm_excursion(self, api):
        """PRD §4: "POST `/api/temperature-excursions/{id}/confirm` | Confirm a
        breach; fires the quarantine cascade; reporter barred | QualityManager".
        PRD §2.9: "Role authorization, applied to all endpoints: the caller's role
        is listed among the endpoint's authorized roles; otherwise
        `ERR_FORBIDDEN`."

        Design: Corner/rbac/warehouse_operator_cannot_confirm_excursion
        """
        zone = create_zone("FZ-RX", capacity_pallets=5, dock_doors=1)
        excursion = report_excursion(zone["id"], reporter_user_id="op-1")
        # A different operator identity, so only the role check can fire.
        resp = api.confirm_temperature_excursion(
            excursion["id"],
            {"X-User-ID": "op-2", "X-User-Role": "WarehouseOperator",
             "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        assert get_excursion(excursion["id"])["status"] == "REPORTED"

    def test_claims_adjuster_cannot_run_billing(self, api):
        """PRD §4: "POST `/api/billing/run` | Finalize every due OPEN invoice and
        open each customer's next-month invoice | BillingAdmin".
        PRD §2.1: "Access to specific operations is restricted by role; an attempt
        to perform an action outside the caller's designated role is rejected with
        `ERR_FORBIDDEN`."

        Design: Corner/rbac/claims_adjuster_cannot_run_billing
        """
        resp = api.run_billing(ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


class TestCustomerOwnership:
    def test_customer_admin_cannot_read_other_customers_order(self, api):
        """PRD §2.1: "A `CustomerAdmin` touching a resource whose `customer_id`
        belongs to a different customer is rejected with `ERR_FORBIDDEN`, and this
        ownership rule extends to reads: a `CustomerAdmin` sees only their own
        receipts, orders, lots, pallets, bookings, excursions, recalls, claims,
        and invoices."

        Design: Corner/rbac/customer_admin_cannot_read_other_customers_order
        """
        customer_a = create_customer("Own A")
        customer_b = create_customer("Own B")
        order = create_order(customer_a["id"], requested_pallets=1)
        resp = api.get_outbound_order(
            order["id"], make_customer_admin_headers(customer_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        operator_view = validate_success(
            api.get_outbound_order(order["id"], OPERATOR))
        assert operator_view["status"] == "DRAFT", (
            "opaque roles read any customer's order")


class TestSafetyBeatsFiscal:
    def _setup_recalled_lot_broke_customer(self):
        """1 pallet of lot L1 received (handling_in 1000 accrued against a credit
        limit of 1), then the lot is recalled. Both a food-safety violation
        (RECALLED lot override) and a fiscal violation (credit) hold at submit."""
        customer, _card = create_customer_with_card("Safety Co",
                                                    credit_limit_cents=1)
        zone = create_zone("FZ-12", capacity_pallets=10, dock_doors=2)
        receive_stock(customer["id"], zone["id"], 1, lot_code="L1")
        recall = declare_recall(customer["id"], product_code="PEAS", lot_code="L1",
                                reason="allergen")
        activate_recall(recall["id"])
        order = create_order(customer["id"], requested_pallets=1, lot_code="L1")
        return customer, order

    def test_lot_recalled_error_wins_over_credit_error(self, api):
        """PRD §2.9: "A request that would fail at several tiers is rejected with
        the error belonging to the earliest applicable tier, so that a failure
        deeper in the cascade never masks one nearer the surface."
        PRD §2.9: "Food-safety gates, applied to order submission and to excursion
        confirmation and clearing: an order submitted with a `lot_code` override
        whose lot stands at `RECALLED` is rejected `ERR_LOT_RECALLED`, and the
        segregation-of-duties check on excursion adjudication is rejected
        `ERR_SOD_VIOLATION`." (tier 7, ahead of the tier-11 fiscal gates)

        Design: Difficulty/priority_pair_validation_conflict/safety_recall_beats_fiscal_credit_on_submit
        """
        customer, order = self._setup_recalled_lot_broke_customer()
        resp = api.submit_outbound_order(
            order["id"], make_customer_admin_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_LOT_RECALLED, expected_status=409)

    def test_rejected_submit_leaves_order_draft(self, api):
        """PRD §3.5: "The order is born `DRAFT`, with `allocated_pallets` at zero
        and `final_handling_out_cents` null, a value it keeps until the order
        ships."
        PRD §2.9: "A request that would fail at several tiers is rejected with the
        error belonging to the earliest applicable tier, so that a failure deeper
        in the cascade never masks one nearer the surface."

        Design: Difficulty/priority_pair_validation_conflict/safety_recall_beats_fiscal_credit_on_submit
        """
        customer, order = self._setup_recalled_lot_broke_customer()
        resp = api.submit_outbound_order(
            order["id"], make_customer_admin_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_LOT_RECALLED)
        after = get_order(order["id"])
        assert after["status"] == "DRAFT", "a rejected submission changes nothing"
        assert after["allocated_pallets"] == 0
