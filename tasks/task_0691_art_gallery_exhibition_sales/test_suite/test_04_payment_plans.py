"""Payment plans: installment schedule (floor + remainder on final), the default
sweep boundary, overpayment guard, the not-invoiced guard, and the sale-version
optimistic-concurrency check on payments."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    setup_invoiced_sale, setup_invoiced_sale_with_plan,
    create_payment_plan, set_clock,
    TEST_USERS,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["gallery_admin_headers"]
SALES = TEST_USERS["sales_associate_headers"]


class TestInstallmentSchedule:
    def test_remainder_loaded_on_final_installment(self, api):
        """PRD §3.6: "The base per-installment amount, `installment_cents`, is the
        buyer total divided by `installment_count` discarding any fractional cent
        (floor division). The remainder — the buyer total minus `installment_cents`
        multiplied by `installment_count` — is loaded entirely onto the last
        installment, so `final_installment_cents` equals `installment_cents` plus
        that remainder."

        Design: Difficulty/combinatorial_formula/installment_remainder_loaded_on_final
        """
        # buyer_total 983750 (gross 1000000, 10% discount, CA buyer rate 875, shipping 5000).
        gallery, artist, artwork, invoiced = setup_invoiced_sale(
            gallery_overrides={"home_state_code": "CA", "sales_tax_rate_bps": 875,
                               "default_consignment_split_bps": 5000},
            artwork_overrides={"list_price_cents": 1_000_000,
                               "insured_value_cents": 1_000_000},
            sale_overrides={"buyer_state_code": "CA", "gross_amount_cents": 1_000_000,
                            "discount_bps": 1000, "shipping_cents": 5000})
        assert invoiced["buyer_total_cents"] == 983750
        plan = validate_success(api.create_payment_plan(
            f.create_payment_plan_payload(invoiced["id"], installment_count=3,
                                          cadence_days=30,
                                          first_due_utc="2026-05-01T00:00:00Z"),
            SALES), 201)
        # floor(983750/3) = 327916; remainder = 983750 - 327916*3 = 2.
        assert plan["installment_cents"] == 327916, \
            f"base installment should be 327916, got {plan['installment_cents']}"
        assert plan["final_installment_cents"] == 327918, \
            f"final installment carries the +2 remainder, got {plan['final_installment_cents']}"

    def test_final_installment_balances_buyer_total(self, api):
        """PRD §3.6: "Installments 1 through the second-to-last each equal
        `installment_cents`; only the final installment carries the remainder,
        which is never spread across the earlier ones."

        Design: Difficulty/combinatorial_formula/installment_remainder_loaded_on_final
        """
        gallery, artist, artwork, invoiced = setup_invoiced_sale(
            gallery_overrides={"home_state_code": "CA", "sales_tax_rate_bps": 875,
                               "default_consignment_split_bps": 5000},
            artwork_overrides={"list_price_cents": 1_000_000,
                               "insured_value_cents": 1_000_000},
            sale_overrides={"buyer_state_code": "CA", "gross_amount_cents": 1_000_000,
                            "discount_bps": 1000, "shipping_cents": 5000})
        plan = validate_success(api.create_payment_plan(
            f.create_payment_plan_payload(invoiced["id"], installment_count=3,
                                          cadence_days=30,
                                          first_due_utc="2026-05-01T00:00:00Z"),
            SALES), 201)
        n = plan["installment_count"]
        total = plan["installment_cents"] * (n - 1) + plan["final_installment_cents"]
        assert total == invoiced["buyer_total_cents"], \
            "(n-1) base installments + final must sum to the buyer total"


class TestPlanDefaultAndGuards:
    def test_plan_defaults_at_exactly_two_missed(self, api):
        """PRD §3.6: "the sweep requires the plan to be `ACTIVE` and moves it
        `ACTIVE → DEFAULTED` when `missed_installment_count` is at least 2; below
        that the sweep is a no-op."
        PRD §3.6: "installment number `k` is due once the clock has reached or
        passed `first_due_utc` plus `(k − 1)` times `cadence_days`".

        Design: Corner/state_machines/payment_plan_default_boundary_exact_two_missed
        """
        gallery, artist, artwork, invoiced = setup_invoiced_sale(
            gallery_overrides={"home_state_code": "CA", "sales_tax_rate_bps": 875},
            artwork_overrides={"list_price_cents": 1_000_000,
                               "insured_value_cents": 1_000_000},
            sale_overrides={"buyer_state_code": "NY", "gross_amount_cents": 1_000_000})
        plan = create_payment_plan(invoiced["id"], installment_count=3,
                                   cadence_days=30,
                                   first_due_utc="2026-05-01T00:00:00Z")
        # Clock to 2026-05-31: installments #1 (05-01) and #2 (05-31) are due, 0 posted.
        set_clock("2026-05-31T00:00:00Z")
        swept = validate_success(api.sweep_overdue_plan(plan["id"], SALES))
        assert swept["missed_installment_count"] == 2, "two installments due, none posted"
        assert swept["status"] == "DEFAULTED", "missed == 2 triggers default"

    def test_overpayment_on_second_payment_rejected(self, api):
        """PRD §3.5: "A posting that would push `amount_collected_cents` strictly
        above `buyer_total_cents` is rejected with `ERR_OVERPAYMENT`."

        Design: Corner/validations/overpayment_rejected_on_second_payment
        """
        gallery, artist, artwork, invoiced = setup_invoiced_sale(
            sale_overrides={"buyer_state_code": "NY", "gross_amount_cents": 400_000})
        # buyer_total 400000; pay 300000 -> PARTIALLY_PAID.
        partial = get_success_data(api.post_payment(
            invoiced["id"], f.payment_payload(300_000, invoiced["version"]), SALES))
        assert partial["settlement_status"] == "PARTIALLY_PAID"
        # Second payment of 150000 would reach 450000 > 400000.
        resp = api.post_payment(
            invoiced["id"], f.payment_payload(150_000, partial["version"]), SALES)
        validate_error(resp, ApiErrorId.ERR_OVERPAYMENT.value)

    def test_plan_on_non_invoiced_sale_rejected(self, api):
        """PRD §3.6: "The linked sale must be in `INVOICED` state; a plan created
        against a sale not in that state is rejected with
        `ERR_PLAN_SALE_NOT_INVOICED`."

        Design: Corner/validations/payment_plan_on_non_invoiced_sale_rejected
        """
        # A RESERVED (never invoiced) sale.
        from test_helpers import setup_reserved_sale
        gallery, artist, artwork, sale = setup_reserved_sale(
            sale_overrides={"buyer_state_code": "NY", "gross_amount_cents": 300_000})
        resp = api.create_payment_plan(
            f.create_payment_plan_payload(sale["id"], installment_count=3,
                                          cadence_days=30,
                                          first_due_utc="2026-05-01T00:00:00Z"),
            SALES)
        validate_error(resp, ApiErrorId.ERR_PLAN_SALE_NOT_INVOICED.value)


class TestPaymentOptimisticConcurrency:
    def test_stale_sale_version_rejected(self, api):
        """PRD §2.9: "Posting a payment against a sale requires the field
        `expected_sale_version` in the request body, carrying the `version` of the
        target `Sale` that the client last observed. If that value does not equal
        the sale's current `version`, the payment is rejected with
        `ERR_STALE_VERSION` at HTTP 412".

        Design: Corner/cross_cutting_complexity_layers/occ_payment_stale_sale_version
        """
        gallery, artist, artwork, invoiced = setup_invoiced_sale(
            sale_overrides={"buyer_state_code": "NY", "gross_amount_cents": 400_000})
        stale_version = invoiced["version"]
        # First payment succeeds and bumps the sale version.
        get_success_data(api.post_payment(
            invoiced["id"], f.payment_payload(100_000, stale_version), SALES))
        # Replaying the pre-payment version is now stale.
        resp = api.post_payment(
            invoiced["id"], f.payment_payload(100_000, stale_version), SALES)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)

    def test_each_payment_with_current_version_succeeds(self, api):
        """PRD §2.9: "where these two endpoints succeed they increment the parent's
        `version` as part of the write."
        PRD §3.5: "The posted `amount_cents` is added to `amount_collected_cents`
        and the sale's `version` is incremented."

        Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_each_payment
        """
        gallery, artist, artwork, invoiced = setup_invoiced_sale(
            sale_overrides={"buyer_state_code": "NY", "gross_amount_cents": 400_000})
        p1 = get_success_data(api.post_payment(
            invoiced["id"], f.payment_payload(100_000, invoiced["version"]), SALES))
        # Use the version returned by the prior response for the next post.
        p2 = get_success_data(api.post_payment(
            invoiced["id"], f.payment_payload(100_000, p1["version"]), SALES))
        assert p2["amount_collected_cents"] == 200000, "two payments accumulate to 200000"
        assert p2["settlement_status"] == "PARTIALLY_PAID"
        assert p2["version"] > p1["version"], "each successful payment bumps version"
