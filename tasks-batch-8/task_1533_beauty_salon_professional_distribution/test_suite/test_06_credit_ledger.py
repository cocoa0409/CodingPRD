"""Education-credit ledger: dual accrual variants, redemption checks, and the
signed-balance invariant across cancellation (PRD §3.5, §3.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_order,
    assert_credit_entry,
    create_active_salon,
    create_draft_order,
    deliver_order_fully,
    list_credit_ledger,
    make_brand,
    make_product,
    make_salon_buyer_headers,
    override_salon_tier,
    setup_salon_with_credit_points,
    submit_order,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _deliver_in_full(api, order_id):
    approve_order(order_id)
    return deliver_order_fully(order_id)


class TestProvisionalVsFinalAccrual:
    def _setup_gold_order_submitted(self, api):
        """ACTIVE salon overridden to GOLD; order of 10 x RETAIL 10000-cent
        units submitted (merch 90000 after the GOLD tier discount)."""
        salon, _ = create_active_salon(tier="GOLD")
        brand = make_brand()
        product = make_product(brand["id"], base_price_cents=10000,
                               weight_grams=250)
        order = create_draft_order(
            salon["id"], [{"product_id": product["id"], "quantity": 10}])
        assert order["merchandise_total_cents"] == 90000
        submit_order(order["id"], salon["id"])
        return salon, order

    def test_provisional_accrual_uses_tier_at_submit(self, api):
        """PRD §3.9: "At order submit, a `PROVISIONAL_ACCRUAL` entry posts:
        the point value is the floor of `net_merch_cents` divided by 1000,
        multiplied by the tier multiplier — 1 for `SILVER`, 2 for `GOLD`, 3
        for `PLATINUM` — using the salon's tier at submit time."

        Design: Difficulty/dual_variant_calc/education_accrual_provisional_vs_final
        """
        salon, order = self._setup_gold_order_submitted(api)
        entries = [e for e in list_credit_ledger(salon["id"])
                   if e.get("order_id") == order["id"]]
        provisional = [e for e in entries
                       if e["entry_type"] == "PROVISIONAL_ACCRUAL"]
        assert len(provisional) == 1
        assert provisional[0]["points"] == 180, (
            "floor(90000/1000) * GOLD multiplier 2 == 180")
        salon_after = validate_success(
            api.get_salon_account(salon["id"], ADMIN), 200)
        assert salon_after["education_credit_points"] == 180

    def test_final_accrual_posts_delta_using_tier_at_delivery(self, api):
        """PRD §3.9: "At delivery, a `FINAL_ACCRUAL` entry posts as a signed
        delta: the final points are recomputed chronologically over the
        delivered non-promotional lines' `line_total_cents` minus
        `credit_applied_cents`, floored by the same 1000-cent divisor and
        multiplied by the tier multiplier at the salon's tier at delivery
        time, and the posted delta is the final points minus the provisional
        points — the delta may be negative."

        Design: Difficulty/dual_variant_calc/education_accrual_provisional_vs_final
        """
        salon, order = self._setup_gold_order_submitted(api)
        # Tier advances to PLATINUM between submit and delivery.
        override_salon_tier(salon["id"], "PLATINUM")
        _deliver_in_full(api, order["id"])

        entries = [e for e in list_credit_ledger(salon["id"])
                   if e.get("order_id") == order["id"]]
        final = [e for e in entries if e["entry_type"] == "FINAL_ACCRUAL"]
        assert len(final) == 1
        assert final[0]["points"] == 90, (
            "final 270 (floor(90000/1000) * PLATINUM 3) - provisional 180 == 90")

        salon_after = validate_success(
            api.get_salon_account(salon["id"], ADMIN), 200)
        assert salon_after["tier"] == "PLATINUM"
        assert salon_after["education_credit_points"] == 270, (
            "180 provisional + 90 final delta == 270")


class TestLedgerBalanceInvariantOnCancel:
    def _setup_submitted_order_with_redemption(self, api):
        """SILVER salon with 1000 points; second order merch 120000 with a
        600-point redemption, SUBMITTED (balance 460)."""
        salon, _, _ = setup_salon_with_credit_points(1000)
        brand = make_brand()
        mask = make_product(brand["id"], base_price_cents=20000,
                            weight_grams=200)
        order = create_draft_order(
            salon["id"], [{"product_id": mask["id"], "quantity": 6}])
        validate_success(api.redeem_credits(
            order["id"], {"points": 600},
            make_salon_buyer_headers(salon["id"])), 200)
        submit_order(order["id"], salon["id"])
        assert validate_success(
            api.get_salon_account(salon["id"], ADMIN), 200
        )["education_credit_points"] == 460
        return salon, order

    def test_cancel_restores_credit_balance_to_pre_order_value(self, api):
        """PRD §3.6: "Cancelling from `SUBMITTED` additionally voids the
        authorization — payment `AUTHORIZED` → `VOIDED` — and reverses the
        provisional accrual."
        PRD §3.6: "Cancelling from `DRAFT` simply reverses any credit
        redemption (restoring points via a `REVERSAL` entry) and reverses any
        applied promotion redemption with reason `ORDER_CANCELLED`, restoring
        budget."

        Design: Difficulty/compensating_invariant/credit_ledger_balance_invariant_on_cancel
        """
        salon, order = self._setup_submitted_order_with_redemption(api)
        cancelled = validate_success(api.cancel_order(
            order["id"], make_salon_buyer_headers(salon["id"])), 200)
        assert cancelled["payment_status"] == "VOIDED"

        salon_after = validate_success(
            api.get_salon_account(salon["id"], ADMIN), 200)
        assert salon_after["education_credit_points"] == 1000, (
            "redemption reversal +600 and provisional reversal -60 restore "
            "the pre-order balance of 1000")

    def test_cancel_posts_signed_reversals_and_ledger_sum_holds(self, api):
        """PRD §3.9: "The salon's `education_credit_points` is always the
        signed sum of `points` across all its entries, and every posting bumps
        that balance by its signed amount."

        Design: Difficulty/compensating_invariant/credit_ledger_balance_invariant_on_cancel
        """
        salon, order = self._setup_submitted_order_with_redemption(api)
        validate_success(api.cancel_order(
            order["id"], make_salon_buyer_headers(salon["id"])), 200)

        entries = list_credit_ledger(salon["id"])
        order_entries = [e for e in entries if e.get("order_id") == order["id"]]
        reversal_points = sorted(
            e["points"] for e in order_entries if e["entry_type"] == "REVERSAL")
        assert reversal_points == [-60, 600], (
            "expected REVERSAL entries of +600 (redemption unwind) and -60 "
            f"(provisional unwind), got {reversal_points}")

        signed_sum = sum(e["points"] for e in entries)
        balance = validate_success(
            api.get_salon_account(salon["id"], ADMIN), 200
        )["education_credit_points"]
        assert signed_sum == balance == 1000, (
            "the signed ledger sum always equals the stored balance")


class TestLedgerEntryShapeAndRedemptionChecks:
    def test_credit_ledger_entries_have_no_version_field(self, api):
        """PRD §2.5: "One entity is exempt: `EducationCreditEntry` is an
        append-only ledger row and carries only `id` and `created_at`; both
        `updated_at` and `version` are absent from it."

        Design: Corner/entities/credit_ledger_entries_have_no_version_field
        """
        salon, _ = create_active_salon()
        brand = make_brand()
        product = make_product(brand["id"], base_price_cents=10000)
        order = create_draft_order(
            salon["id"], [{"product_id": product["id"], "quantity": 1}])
        submit_order(order["id"], salon["id"])

        entries = list_credit_ledger(salon["id"])
        assert len(entries) == 1
        entry = entries[0]
        assert_credit_entry(entry)
        assert entry["entry_type"] == "PROVISIONAL_ACCRUAL"
        assert entry["points"] == 10
        assert "version" not in entry, "ledger rows carry no version"
        assert "updated_at" not in entry, "ledger rows carry no updated_at"

    def test_credit_redemption_over_cap_returns_422(self, api):
        """PRD §3.5: "Two checks are evaluated in a pinned order: first, the
        requested points must not exceed the salon's redeemable points — the
        sum over the salon's accrual entries of `points` minus
        `consumed_points`, counting only entries whose `expires_at` still lies
        after the logical clock — else `ERR_INSUFFICIENT_CREDIT_BALANCE`
        (HTTP 422); second, the requested cents (points times 100) must not
        exceed the cap, which is the floor of half the order's
        `merchandise_total_cents` — else `ERR_CREDIT_REDEMPTION_EXCEEDS_CAP`
        (HTTP 422)."

        Design: Corner/validations/credit_redemption_over_cap_returns_422
        """
        salon, _, _ = setup_salon_with_credit_points(100)
        brand = make_brand()
        mini = make_product(brand["id"], base_price_cents=10000)
        order = create_draft_order(
            salon["id"], [{"product_id": mini["id"], "quantity": 1}])
        assert order["merchandise_total_cents"] == 10000

        resp = api.redeem_credits(
            order["id"], {"points": 60},
            make_salon_buyer_headers(salon["id"]))
        validate_error(resp, ApiErrorId.ERR_CREDIT_REDEMPTION_EXCEEDS_CAP)
        refreshed = validate_success(api.get_order(order["id"], ADMIN), 200)
        assert refreshed["credit_applied_cents"] == 0, (
            "a rejected redemption applies nothing (cap 5000 < 6000 requested)")

    def test_credit_redemption_over_balance_returns_422(self, api):
        """PRD §3.5: "Two checks are evaluated in a pinned order: first, the
        requested points must not exceed the salon's redeemable points — the
        sum over the salon's accrual entries of `points` minus
        `consumed_points`, counting only entries whose `expires_at` still lies
        after the logical clock — else `ERR_INSUFFICIENT_CREDIT_BALANCE`
        (HTTP 422); second, the requested cents (points times 100) must not
        exceed the cap, which is the floor of half the order's
        `merchandise_total_cents` — else `ERR_CREDIT_REDEMPTION_EXCEEDS_CAP`
        (HTTP 422)."

        Design: Corner/validations/credit_redemption_over_balance_returns_422
        """
        salon, _, _ = setup_salon_with_credit_points(10)
        brand = make_brand()
        kit = make_product(brand["id"], base_price_cents=100000,
                           weight_grams=900)
        order = create_draft_order(
            salon["id"], [{"product_id": kit["id"], "quantity": 1}])

        resp = api.redeem_credits(
            order["id"], {"points": 20},
            make_salon_buyer_headers(salon["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIT_BALANCE)
