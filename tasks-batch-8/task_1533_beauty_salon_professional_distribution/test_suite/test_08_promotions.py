"""Promotions: lifecycle, redemption waterfall gates, budget invariants, and
the OCC budget-adjustment guard (PRD §3.5, §3.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_salon,
    create_bundle_promotion,
    create_draft_order,
    create_sample_promotion,
    get_order,
    get_promotion,
    list_order_line_items,
    list_redemptions,
    make_brand,
    make_product,
    make_salon_buyer_headers,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _salon_brand_products(price=10000, sample_price=500):
    salon, _ = create_active_salon()
    brand = make_brand()
    product = make_product(brand["id"], base_price_cents=price)
    sample = make_product(brand["id"], base_price_cents=sample_price,
                          weight_grams=10)
    return salon, product, sample


class TestPromotionLifecycle:
    def test_promotion_duplicate_code_returns_409(self, api):
        """PRD §3.8: "A `DistributionAdmin` authors a promotion with a unique
        `code` (duplicates yield `ERR_DUPLICATE_CODE`), a `promo_type`, a
        non-empty `eligible_tiers` subset of the tier enumeration, an
        inclusive `starts_at`, an exclusive `ends_at` strictly after
        `starts_at` (`ERR_INVALID_TIME_WINDOW` otherwise), a strictly positive
        `budget_units`, and a strictly positive `per_salon_cap`."

        Design: Corner/validations/promotion_duplicate_code_returns_409
        """
        brand = make_brand()
        sample = make_product(brand["id"], base_price_cents=500,
                              weight_grams=10)
        create_sample_promotion(sample["id"], code="DUP1", activate=False)

        resp = api.create_promotion(
            {"code": "DUP1", "promo_type": "SAMPLE", "eligible_tiers": ["GOLD"],
             "starts_at": "2026-07-01T00:00:00Z", "ends_at": "2027-01-01T00:00:00Z",
             "budget_units": 2, "per_salon_cap": 1,
             "sample_product_id": sample["id"], "sample_units_per_redemption": 1},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CODE)

    def test_promotion_pause_resume_cycle(self, api):
        """PRD §3.8: "An `ACTIVE` promotion may be paused — manually by an
        administrator, or automatically when a referenced product (required,
        free, or sample) becomes `DISCONTINUED`. Resuming a `PAUSED` promotion
        re-checks the window against the logical clock
        (`ERR_INVALID_TIME_WINDOW`) and requires every referenced product to
        be `ACTIVE` or `LIQUIDATION` (`ERR_INVALID_PRODUCT_STATE` otherwise)."
        PRD §3.8: "Activation requires `DRAFT` (`ERR_INVALID_PROMOTION_STATE`
        otherwise) and re-checks that `ends_at` still lies after the logical
        clock (`ERR_INVALID_TIME_WINDOW` otherwise); on success
        `remaining_budget_units` initializes to `budget_units`."

        Design: Corner/state_machines/promotion_pause_resume_cycle
        """
        brand = make_brand()
        sample = make_product(brand["id"], base_price_cents=500,
                              weight_grams=10)
        promo = create_sample_promotion(
            sample["id"], code="SAMP7", budget_units=4, per_salon_cap=2)
        assert promo["remaining_budget_units"] == 4

        paused = validate_success(api.pause_promotion(promo["id"], ADMIN), 200)
        assert paused["status"] == "PAUSED"
        assert paused["remaining_budget_units"] == 4

        resumed = validate_success(api.resume_promotion(promo["id"], ADMIN), 200)
        assert resumed["status"] == "ACTIVE"
        assert resumed["remaining_budget_units"] == 4, (
            "the pause/resume cycle must not re-initialize the budget")


class TestSampleRedemption:
    def test_sample_budget_exhaustion_ends_promotion(self, api):
        """PRD §3.5: "If the decrement drives `remaining_budget_units` to
        exactly zero, the promotion moves from `ACTIVE` to `ENDED` at once."

        Design: Corner/calculations/sample_budget_exhaustion_ends_promotion
        """
        salon, product, sample = _salon_brand_products()
        promo = create_sample_promotion(
            sample["id"], code="SAMP20", budget_units=2, per_salon_cap=10,
            sample_units_per_redemption=2)
        order = create_draft_order(
            salon["id"], [{"product_id": product["id"], "quantity": 1}])

        validate_success(api.redeem_promotion(
            order["id"], {"code": "SAMP20"},
            make_salon_buyer_headers(salon["id"])), 200)
        refreshed = get_promotion(promo["id"])
        assert refreshed["remaining_budget_units"] == 0
        assert refreshed["status"] == "ENDED", (
            "a redemption consuming the last budgeted units ends the promotion")

    def test_cancel_restores_promotion_budget(self, api):
        """PRD §3.6: "Whenever a redemption reverses, the promotion's
        `remaining_budget_units` grows back by `units_consumed` — but a
        promotion that has already ended stays `ENDED`."

        Design: Difficulty/compensating_invariant/promotion_budget_invariant_on_cancel
        """
        salon, product, sample = _salon_brand_products()
        promo = create_sample_promotion(
            sample["id"], code="SAMP9", budget_units=5, per_salon_cap=10,
            sample_units_per_redemption=2)
        order = create_draft_order(
            salon["id"], [{"product_id": product["id"], "quantity": 1}])
        validate_success(api.redeem_promotion(
            order["id"], {"code": "SAMP9"},
            make_salon_buyer_headers(salon["id"])), 200)
        assert get_promotion(promo["id"])["remaining_budget_units"] == 3

        validate_success(api.cancel_order(
            order["id"], make_salon_buyer_headers(salon["id"])), 200)
        refreshed = get_promotion(promo["id"])
        assert refreshed["remaining_budget_units"] == 5, (
            "cancelling the order reverses the redemption and restores budget")

    def test_cancel_marks_redemption_reversed_and_order_cancelled(self, api):
        """PRD §3.6: "Cancelling from `DRAFT` simply reverses any credit
        redemption (restoring points via a `REVERSAL` entry) and reverses any
        applied promotion redemption with reason `ORDER_CANCELLED`, restoring
        budget."

        Design: Difficulty/compensating_invariant/promotion_budget_invariant_on_cancel
        """
        salon, product, sample = _salon_brand_products()
        promo = create_sample_promotion(
            sample["id"], code="SAMP9B", budget_units=5, per_salon_cap=10,
            sample_units_per_redemption=2)
        order = create_draft_order(
            salon["id"], [{"product_id": product["id"], "quantity": 1}])
        validate_success(api.redeem_promotion(
            order["id"], {"code": "SAMP9B"},
            make_salon_buyer_headers(salon["id"])), 200)
        redemption = [r for r in list_redemptions()
                      if r["order_id"] == order["id"]][0]

        cancelled = validate_success(api.cancel_order(
            order["id"], make_salon_buyer_headers(salon["id"])), 200)
        assert cancelled["fulfillment_status"] == "CANCELLED"

        after = validate_success(
            api.get_promotion_redemption(redemption["id"], ADMIN), 200)
        assert after["status"] == "REVERSED"
        assert after["reversal_reason"] == "ORDER_CANCELLED"


class TestRedemptionWaterfallGates:
    def test_promo_redeem_before_window_returns_409(self, api):
        """PRD §3.5: "**Window** — the logical clock must satisfy: at or after the
        promotion's `starts_at` and strictly before its `ends_at`; otherwise
        `ERR_PROMOTION_NOT_ACTIVE` (HTTP 409)."

        Design: Corner/validations/promo_redeem_before_window_returns_409
        """
        salon, product, sample = _salon_brand_products()
        create_sample_promotion(
            sample["id"], code="FUT31", budget_units=5, per_salon_cap=5,
            starts_at="2026-09-01T00:00:00Z", ends_at="2026-12-01T00:00:00Z")
        order = create_draft_order(
            salon["id"], [{"product_id": product["id"], "quantity": 1}])

        resp = api.redeem_promotion(
            order["id"], {"code": "FUT31"},
            make_salon_buyer_headers(salon["id"]))
        validate_error(resp, ApiErrorId.ERR_PROMOTION_NOT_ACTIVE)

    def test_promo_redeem_while_draft_returns_409(self, api):
        """PRD §3.5: "Redeeming against a promotion in `DRAFT`, `PAUSED`, or
        `ENDED` state is rejected with `ERR_INVALID_PROMOTION_STATE`
        (HTTP 409), and an unknown code is `ERR_PROMOTION_NOT_FOUND` (404)."

        Design: Corner/validations/promo_redeem_while_draft_returns_409
        """
        salon, product, sample = _salon_brand_products()
        create_sample_promotion(
            sample["id"], code="DRF32", budget_units=5, per_salon_cap=5,
            activate=False)
        order = create_draft_order(
            salon["id"], [{"product_id": product["id"], "quantity": 1}])

        resp = api.redeem_promotion(
            order["id"], {"code": "DRF32"},
            make_salon_buyer_headers(salon["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_PROMOTION_STATE)

    def test_promo_budget_exhausted_returns_422(self, api):
        """PRD §3.5: "**Budget bucket** — the redemption consumes `free_qty`
        units for a `BUNDLE` or `sample_units_per_redemption` units for a
        `SAMPLE`; if the promotion's `remaining_budget_units` is smaller than
        that consumption, the redemption is rejected with
        `ERR_PROMOTION_BUDGET_EXHAUSTED` (HTTP 422) — there are no partial
        grants."

        Design: Corner/validations/promo_budget_exhausted_returns_422
        """
        salon, product, sample = _salon_brand_products()
        promo = create_sample_promotion(
            sample["id"], code="BUD33", budget_units=1, per_salon_cap=5,
            sample_units_per_redemption=2)
        order = create_draft_order(
            salon["id"], [{"product_id": product["id"], "quantity": 1}])

        resp = api.redeem_promotion(
            order["id"], {"code": "BUD33"},
            make_salon_buyer_headers(salon["id"]))
        validate_error(resp, ApiErrorId.ERR_PROMOTION_BUDGET_EXHAUSTED)
        refreshed = get_promotion(promo["id"])
        assert refreshed["remaining_budget_units"] == 1, "no partial grants"
        assert refreshed["status"] == "ACTIVE"

    def test_promo_per_salon_cap_returns_422(self, api):
        """PRD §3.5: "**Per-salon bucket** — the salon's units already consumed on
        this promotion (the sum of `units_consumed` over `APPLIED` redemptions
        of the promotion by this salon) plus this redemption's units must not
        exceed `per_salon_cap`, else `ERR_PER_SALON_CAP_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/promo_per_salon_cap_returns_422
        """
        salon, product, sample = _salon_brand_products()
        promo = create_sample_promotion(
            sample["id"], code="CAP34", budget_units=10, per_salon_cap=2,
            sample_units_per_redemption=2)
        order1 = create_draft_order(
            salon["id"], [{"product_id": product["id"], "quantity": 1}])
        validate_success(api.redeem_promotion(
            order1["id"], {"code": "CAP34"},
            make_salon_buyer_headers(salon["id"])), 200)

        order2 = create_draft_order(
            salon["id"], [{"product_id": product["id"], "quantity": 1}])
        resp = api.redeem_promotion(
            order2["id"], {"code": "CAP34"},
            make_salon_buyer_headers(salon["id"]))
        validate_error(resp, ApiErrorId.ERR_PER_SALON_CAP_EXCEEDED)
        assert get_promotion(promo["id"])["remaining_budget_units"] == 8, (
            "only the first redemption consumed budget (10 - 2 == 8)")

    def test_promo_tier_ineligible_returns_422(self, api):
        """PRD §3.5: "**Tier eligibility** — the salon's tier must appear in the
        promotion's `eligible_tiers`, else `ERR_PROMOTION_TIER_INELIGIBLE`
        (HTTP 422)."

        Design: Corner/validations/promo_tier_ineligible_returns_422
        """
        salon, product, sample = _salon_brand_products()
        create_sample_promotion(
            sample["id"], code="GLD37", budget_units=5, per_salon_cap=5,
            eligible_tiers=["GOLD"])
        order = create_draft_order(
            salon["id"], [{"product_id": product["id"], "quantity": 1}])

        resp = api.redeem_promotion(
            order["id"], {"code": "GLD37"},
            make_salon_buyer_headers(salon["id"]))
        validate_error(resp, ApiErrorId.ERR_PROMOTION_TIER_INELIGIBLE)

    def test_promo_already_applied_returns_409(self, api):
        """PRD §3.5: "**Uniqueness on the order** — the same promotion must not
        already have an `APPLIED` redemption on this order, else
        `ERR_PROMOTION_ALREADY_APPLIED` (HTTP 409)."

        Design: Corner/validations/promo_already_applied_returns_409
        """
        salon, product, sample = _salon_brand_products()
        promo = create_sample_promotion(
            sample["id"], code="DUP38", budget_units=10, per_salon_cap=10)
        order = create_draft_order(
            salon["id"], [{"product_id": product["id"], "quantity": 1}])
        validate_success(api.redeem_promotion(
            order["id"], {"code": "DUP38"},
            make_salon_buyer_headers(salon["id"])), 200)

        resp = api.redeem_promotion(
            order["id"], {"code": "DUP38"},
            make_salon_buyer_headers(salon["id"]))
        validate_error(resp, ApiErrorId.ERR_PROMOTION_ALREADY_APPLIED)
        assert get_promotion(promo["id"])["remaining_budget_units"] == 9, (
            "only the first redemption consumed budget")


class TestBundleRedemption:
    def test_bundle_requirement_not_met_returns_422(self, api):
        """PRD §3.5: "**Bundle requirement** — for a `BUNDLE` promotion only, the
        order must contain at least `required_qty` non-promotional units of
        `required_product_id`, else `ERR_BUNDLE_REQUIREMENT_NOT_MET`
        (HTTP 422)."

        Design: Corner/validations/bundle_requirement_not_met_returns_422
        """
        salon, _ = create_active_salon()
        brand = make_brand()
        required = make_product(brand["id"], base_price_cents=10000)
        free = make_product(brand["id"], base_price_cents=4000)
        create_bundle_promotion(
            required["id"], 4, free["id"], 1, code="BUN35")
        order = create_draft_order(
            salon["id"], [{"product_id": required["id"], "quantity": 2}])

        resp = api.redeem_promotion(
            order["id"], {"code": "BUN35"},
            make_salon_buyer_headers(salon["id"]))
        validate_error(resp, ApiErrorId.ERR_BUNDLE_REQUIREMENT_NOT_MET)

    def test_bundle_redemption_adds_free_line(self, api):
        """PRD §3.5: "On success the grant is materialized: a zero-priced
        promotional `OrderItem` is injected — `free_product_id` times
        `free_qty` for a bundle, `sample_product_id` times
        `sample_units_per_redemption` for a sample — with `is_promotional`
        true and `unit_price_cents` zero; a `PromotionRedemption` is created
        in `APPLIED`, recording the `promotion_id`, the order's `order_id`,
        the redeeming salon's `salon_account_id`, and `units_consumed` set to
        the consumed units; `remaining_budget_units` is decremented by the
        same amount; the order's `promo_applied_code` records the code; and
        the order's `version` increments."

        Design: Corner/validations/bundle_redemption_adds_free_line
        """
        salon, _ = create_active_salon()
        brand = make_brand()
        required = make_product(brand["id"], base_price_cents=10000)
        free = make_product(brand["id"], base_price_cents=4000)
        promo = create_bundle_promotion(
            required["id"], 4, free["id"], 1, code="BUN36")
        order = create_draft_order(
            salon["id"], [{"product_id": required["id"], "quantity": 4}])

        redeemed = validate_success(api.redeem_promotion(
            order["id"], {"code": "BUN36"},
            make_salon_buyer_headers(salon["id"])), 200)
        assert redeemed["promo_applied_code"] == "BUN36"
        assert redeemed["merchandise_total_cents"] == 40000, (
            "the promotional line contributes zero to merchandise_total_cents")

        items = list_order_line_items(order["id"])
        assert len(items) == 2
        promo_lines = [it for it in items if it["is_promotional"]]
        assert len(promo_lines) == 1
        line = promo_lines[0]
        assert line["product_id"] == free["id"]
        assert line["quantity"] == 1
        assert line["unit_price_cents"] == 0
        assert get_promotion(promo["id"])["remaining_budget_units"] == 9


class TestRedemptionDiscoveryAndBudgetOcc:
    def test_promotion_redemptions_reverse_reachable(self, api):
        """PRD §3.5: "a `PromotionRedemption` is created in `APPLIED`,
        recording the `promotion_id`, the order's `order_id`, the redeeming
        salon's `salon_account_id`, and `units_consumed` set to the consumed
        units"
        PRD §4: "| GET | /api/promotion-redemptions | List promotion
        redemptions (filtered) | DistributionAdmin, ComplianceOfficer,
        SalonBuyer |"

        Design: Corner/endpoints/promotion_redemptions_reverse_reachable
        """
        salon, product, sample = _salon_brand_products()
        promo = create_sample_promotion(
            sample["id"], code="REV51", budget_units=5, per_salon_cap=5)
        order = create_draft_order(
            salon["id"], [{"product_id": product["id"], "quantity": 1}])
        validate_success(api.redeem_promotion(
            order["id"], {"code": "REV51"},
            make_salon_buyer_headers(salon["id"])), 200)

        redemptions = list_redemptions()
        assert len(redemptions) == 1
        red = redemptions[0]
        assert red["status"] == "APPLIED"
        assert red["units_consumed"] == 1
        assert red["promotion_id"] == promo["id"]
        assert red["order_id"] == order["id"]
        assert red["salon_account_id"] == salon["id"]

    def test_budget_adjust_stale_version_returns_412(self, api):
        """PRD §2.6: "A promotion budget adjustment must carry
        `expected_promotion_version` matching the promotion's current
        `version`. Budget adjustments are otherwise always legal, so an
        advanced version means the caller's view of remaining budget is stale;
        the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.8: "Both `budget_units` and `remaining_budget_units` shift by
        `delta_units`, the result must keep `remaining_budget_units` at zero
        or above (`ERR_INVALID_REQUEST` otherwise), and the promotion's
        `version` increments by 1."

        Design: Corner/cross_cutting_complexity_layers/budget_adjust_stale_version_returns_412
        """
        brand = make_brand()
        sample = make_product(brand["id"], base_price_cents=500,
                              weight_grams=10)
        promo = create_sample_promotion(
            sample["id"], code="OCC47", budget_units=10, per_salon_cap=5)
        observed = get_promotion(promo["id"])["version"]

        adjusted = validate_success(api.adjust_promotion_budget(
            promo["id"],
            {"delta_units": 5, "expected_promotion_version": observed},
            ADMIN), 200)
        assert adjusted["budget_units"] == 15
        assert adjusted["remaining_budget_units"] == 15

        resp = api.adjust_promotion_budget(
            promo["id"],
            {"delta_units": 5, "expected_promotion_version": observed},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        refreshed = get_promotion(promo["id"])
        assert refreshed["budget_units"] == 15
        assert refreshed["remaining_budget_units"] == 15
