"""Demo credits and purchase orders: credit accrual, expiry, aggregation caps,
and redemption gating."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    make_customer,
    make_customer_headers,
    make_demo_credit,
    make_demo_equipment_item,
    make_equipment_item,
    set_clock,
    validate_error,
    validate_success,
)

FD = TEST_USERS["front_desk_headers"]


class TestDemoCreditLifecycle:
    def test_credit_expires_exactly_at_expiry(self, api):
        """PRD Demo Days and Purchase Upgrades: "The credit is born `ACTIVE` and
        expires ninety days after the demo date — `expires_at` is set to midnight UTC
        on the day ninety days out. When the logical clock reaches that instant, the
        credit flips to `EXPIRED`, whether noticed by the clock sweep or on read."

        Design: Corner/state_machines/demo_credit_auto_expires_at_expiry_boundary
        """
        customer = make_customer()
        unit = make_demo_equipment_item()
        credit = make_demo_credit(customer, unit, demo_date="2026-12-01",
                                  fee_paid_cents=5000)
        assert credit["status"] == "ACTIVE"
        assert credit["credit_cents"] == 5000
        # 2026-12-01 + 90 days = 2027-03-01, at midnight UTC.
        assert credit["expires_at"].startswith("2027-03-01T00:00:00"), (
            f"expires_at must be midnight UTC on the day ninety days out, "
            f"got {credit['expires_at']!r}"
        )

        set_clock("2027-03-01T00:00:00Z")  # now == expires_at: boundary is inclusive
        after = validate_success(api.get_demo_credit(credit["id"], FD))
        assert after["status"] == "EXPIRED"

    def test_demo_day_on_non_demo_unit_rejected(self, api):
        """PRD Demo Days and Purchase Upgrades: "Only `DEMO`-tier units qualify;
        recording a demo day against any other tier is rejected with
        `ERR_NOT_DEMO_TIER`."

        Design: Corner/validations/demo_credit_on_non_demo_tier_rejected
        """
        customer = make_customer()
        unit = make_equipment_item(gear_type="SNOWBOARD", tier="STANDARD",
                                   size_label="156cm", purchase_price_cents=50000,
                                   base_daily_rate_cents=5000)
        resp = api.create_demo_credit(
            {"customer_id": customer["id"], "equipment_item_id": unit["id"],
             "demo_date": "2026-12-01", "fee_paid_cents": 5000},
            FD,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_DEMO_TIER)


class TestPurchasePricing:
    def test_credits_aggregate_below_cap(self, api):
        """PRD Demo Days and Purchase Upgrades: "The total credit is capped at thirty
        percent of the list price, rounded half-up: `credit_applied_cents` is the
        smaller of the summed eligible credits and that cap, and `amount_due_cents` is
        the list price minus the applied credit."
        and "The `list_price_cents` is three quarters of the unit's
        `purchase_price_cents`, rounded half-up, for a `DEMO`-tier unit"

        Design: Corner/calculations/demo_credit_cap_aggregation
        """
        customer = make_customer()
        headers = make_customer_headers(customer["id"])
        du1 = make_demo_equipment_item(size_label="154cm")
        du2 = make_demo_equipment_item(size_label="156cm")
        purchase_unit = make_demo_equipment_item(size_label="158cm",
                                                 purchase_price_cents=60000)
        make_demo_credit(customer, du1, demo_date="2026-12-01", fee_paid_cents=5000)
        make_demo_credit(customer, du2, demo_date="2026-12-05", fee_paid_cents=8000)

        resp = api.create_purchase_order(
            {"customer_id": customer["id"], "equipment_item_id": purchase_unit["id"]},
            headers,
        )
        order = validate_success(resp, expected_status=201)
        # DEMO list = 60000 x 0.75 = 45000; cap = round(0.30 x 45000) = 13500.
        assert order["list_price_cents"] == 45000
        # 5000 + 8000 = 13000 < 13500: both credits aggregate.
        assert order["credit_applied_cents"] == 13000
        assert order["amount_due_cents"] == 32000
        unit_after = validate_success(api.get_equipment_item(purchase_unit["id"], FD))
        assert unit_after["status"] == "RESERVED"


class TestRedemptionGating:
    def _setup_paid_order_with_credit(self, api):
        customer = make_customer()
        headers = make_customer_headers(customer["id"])
        d1 = make_demo_equipment_item(size_label="156cm")
        d2 = make_demo_equipment_item(size_label="158cm")
        d3 = make_demo_equipment_item(size_label="160cm")
        credit = make_demo_credit(customer, d1, demo_date="2026-12-01",
                                  fee_paid_cents=5000)
        po1 = validate_success(api.create_purchase_order(
            {"customer_id": customer["id"], "equipment_item_id": d2["id"],
             "demo_credit_id": credit["id"]},
            headers,
        ), expected_status=201)
        validate_success(api.pay_purchase_order(po1["id"], headers))
        return customer, headers, credit, po1, d3

    def test_paid_order_redeems_applied_credit(self, api):
        """PRD Demo Days and Purchase Upgrades: "Paying moves it from `PENDING` to
        `PAID` and redeems every demo credit applied to the order, flipping each from
        `ACTIVE` to `REDEEMED`."

        Design: Difficulty/cross_entity_state_dependency/purchase_requires_redeemable_demo_credit
        """
        _, _, credit, po1, _ = self._setup_paid_order_with_credit(api)
        # List 37500 on the 50000-price DEMO unit, cap 11250, credit 5000 applied.
        assert po1["amount_due_cents"] == 32500
        redeemed = validate_success(api.get_demo_credit(credit["id"], FD))
        assert redeemed["status"] == "REDEEMED"

    def test_redeemed_credit_cannot_apply_to_second_purchase(self, api):
        """PRD Demo Days and Purchase Upgrades: "a credit that belongs to another
        customer or is not `ACTIVE` is rejected with `ERR_DEMO_CREDIT_NOT_REDEEMABLE`."

        Design: Difficulty/cross_entity_state_dependency/purchase_requires_redeemable_demo_credit
        """
        customer, headers, credit, _, d3 = self._setup_paid_order_with_credit(api)
        resp = api.create_purchase_order(
            {"customer_id": customer["id"], "equipment_item_id": d3["id"],
             "demo_credit_id": credit["id"]},
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_DEMO_CREDIT_NOT_REDEEMABLE)

    def test_expired_credit_rejected_at_purchase(self, api):
        """PRD Demo Days and Purchase Upgrades: "When the caller names a specific
        `demo_credit_id`, that credit must be among the eligible set — the expiry check
        runs first, so a credit whose validity has lapsed is rejected with
        `ERR_DEMO_CREDIT_EXPIRED`"

        Design: Corner/validations/purchase_with_expired_credit_returns_422
        """
        customer = make_customer()
        headers = make_customer_headers(customer["id"])
        du = make_demo_equipment_item(size_label="156cm")
        pu = make_demo_equipment_item(size_label="158cm")
        credit = make_demo_credit(customer, du, demo_date="2026-12-01",
                                  fee_paid_cents=5000)
        set_clock("2027-03-02T00:00:00Z")  # past the 2027-03-01T00:00:00Z expiry

        resp = api.create_purchase_order(
            {"customer_id": customer["id"], "equipment_item_id": pu["id"],
             "demo_credit_id": credit["id"]},
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_DEMO_CREDIT_EXPIRED)
