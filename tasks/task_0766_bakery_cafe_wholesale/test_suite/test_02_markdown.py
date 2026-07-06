"""Shelf-life markdown pricing, eligibility boundary, and optimistic-concurrency guard."""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, get_success_data,
    ApiErrorId, set_clock, make_product, make_oven, make_bake_plan, add_line,
    commit_plan, make_bake_lot, make_retail_sale, get_lot, TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]


def _lot_with_clock(api, clock, baked_qty=20, sell=0, base_price_cents=400,
                    produced_at="2026-06-04T06:00:00Z", production_date="2026-06-04T00:00:00Z"):
    """Committed line + FRESH lot; advance the clock; optionally sell some units.

    Returns the lot dict as observed after any sale (with its current version).
    """
    product = make_product(api, base_price_cents=base_price_cents, shelf_life_hours=12,
                           category="PASTRY")
    oven = make_oven(api)
    plan = make_bake_plan(api, production_date=production_date)
    line = add_line(api, plan["id"], product["id"], 30)
    commit_plan(api, plan["id"])
    set_clock(api, clock)
    lot = make_bake_lot(api, line["id"], oven["id"], baked_qty=baked_qty,
                        produced_at=produced_at,
                        slot_start=produced_at.replace("T06", "T02"),
                        slot_end=produced_at.replace("T06", "T03"))
    if sell:
        make_retail_sale(api, lot["id"], sell)
        lot = get_lot(api, lot["id"])
    return lot


class TestMarkdownTieredPricing:
    def test_markdown_price_combines_tier_discount_and_surplus_bonus(self, api):
        """PRD 3.4: "When more than four hours remain, the base discount is 25%" and "A
        surplus bonus of an additional 15% is added when the remaining ratio — the lot's
        remaining_qty divided by its baked_qty — is at least one half" and "The
        markdown_price_cents is the product's base_price_cents multiplied by one minus the
        final discount, rounded half up to whole cents, and the same value is written to
        current_unit_price_cents."

        Design: Difficulty/combinatorial_formula/markdown_tiered_nonlinear_mode_a
        """
        # clock 12:00 vs best_by 18:00 => h=6 (>4 => 25%); remaining 12/20=0.6 (>=0.5 => +15%)
        lot = _lot_with_clock(api, "2026-06-04T12:00:00Z", baked_qty=20, sell=8)
        result = validate_success(
            api.markdown_bake_lot(lot["id"], {"expected_bake_lot_version": lot["version"]}, MANAGER))
        assert result["markdown_price_cents"] == 240, result   # round(400*(1-0.40))
        assert result["current_unit_price_cents"] == 240, result
        assert result["status"] == "MARKED_DOWN", result

    def test_markdown_increments_lot_version_by_one(self, api):
        """PRD 3.4: "Both the first markdown and every re-markdown require the caller to
        supply expected_bake_lot_version matching the lot's current version and increment
        that version by one on success (see 2.9)."

        Design: Difficulty/combinatorial_formula/markdown_tiered_nonlinear_mode_a
        """
        lot = _lot_with_clock(api, "2026-06-04T12:00:00Z", baked_qty=20, sell=8)
        before = lot["version"]
        result = validate_success(
            api.markdown_bake_lot(lot["id"], {"expected_bake_lot_version": before}, MANAGER))
        assert result["version"] == before + 1, result


class TestMarkdownEligibilityBoundary:
    def test_markdown_eligible_at_exactly_eight_hours_uses_mid_discount(self, api):
        """PRD 3.4: "A markdown is eligible only when that figure is at most eight hours
        and strictly greater than zero" and "When more than four hours remain, the base
        discount is 25%."

        Design: Difficulty/boundary_precision_check/markdown_window_hours_boundary
        """
        # clock 10:00 vs best_by 18:00 => h==8 (eligible, boundary); remaining 3/10=0.3 (<0.5)
        lot = _lot_with_clock(api, "2026-06-06T10:00:00Z", baked_qty=10, sell=7,
                              produced_at="2026-06-06T06:00:00Z",
                              production_date="2026-06-06T00:00:00Z")
        result = validate_success(
            api.markdown_bake_lot(lot["id"], {"expected_bake_lot_version": lot["version"]}, MANAGER))
        assert result["status"] == "MARKED_DOWN", result
        assert result["markdown_price_cents"] == 300, result   # round(400*0.75)

    def test_markdown_rejected_just_beyond_eight_hour_window(self, api):
        """PRD 3.4: "a lot with more than eight hours of life left ... is refused with
        ERR_MARKDOWN_NOT_ELIGIBLE."

        Design: Difficulty/boundary_precision_check/markdown_window_hours_boundary
        """
        # clock 09:00 vs best_by 18:00 => h==9 (> 8, ineligible)
        lot = _lot_with_clock(api, "2026-06-06T09:00:00Z", baked_qty=10, sell=0,
                              produced_at="2026-06-06T06:00:00Z",
                              production_date="2026-06-06T00:00:00Z")
        validate_error(
            api.markdown_bake_lot(lot["id"], {"expected_bake_lot_version": lot["version"]}, MANAGER),
            ApiErrorId.ERR_MARKDOWN_NOT_ELIGIBLE.value)


class TestMarkdownConcurrencyGuard:
    def test_markdown_with_stale_version_after_sale_is_rejected_412(self, api):
        """PRD 2.9: "The markdown request must carry expected_bake_lot_version, a
        non-optional field holding the client's last observed version of the target
        BakeLot. If that value does not equal the lot's current version, the request is
        rejected with ERR_STALE_LOT_VERSION and HTTP 412."

        Design: Corner/cross_cutting_complexity_layers/markdown_stale_version_returns_412
        """
        product = make_product(api, base_price_cents=400, shelf_life_hours=12, category="PASTRY")
        oven = make_oven(api)
        plan = make_bake_plan(api, production_date="2026-06-04T00:00:00Z")
        line = add_line(api, plan["id"], product["id"], 20)
        commit_plan(api, plan["id"])
        set_clock(api, "2026-06-04T12:00:00Z")
        lot = make_bake_lot(api, line["id"], oven["id"], baked_qty=10,
                            produced_at="2026-06-04T06:00:00Z",
                            slot_start="2026-06-04T02:00:00Z", slot_end="2026-06-04T03:00:00Z")
        stale_version = lot["version"]           # observed before the sale
        make_retail_sale(api, lot["id"], 2)      # mutates remaining_qty => bumps lot.version
        validate_error(
            api.markdown_bake_lot(lot["id"], {"expected_bake_lot_version": stale_version}, MANAGER),
            ApiErrorId.ERR_STALE_LOT_VERSION.value)

    def test_markdown_on_expired_lot_is_rejected(self, api):
        """PRD 2.8: "State legality: the target must be in a state from which the requested
        transition is defined, else ERR_INVALID_STATE; plus the state-adjacent guards
        described where they apply (ERR_LOT_EXPIRED, ERR_ACCOUNT_SUSPENDED,
        ERR_ROUTE_NOT_DISPATCHED)."

        Design: Corner/errors/markdown_on_expired_lot_returns_lot_expired
        """
        product = make_product(api, base_price_cents=400, shelf_life_hours=12)
        oven = make_oven(api)
        plan = make_bake_plan(api, production_date="2026-06-30T00:00:00Z")
        line = add_line(api, plan["id"], product["id"], 20)
        commit_plan(api, plan["id"])
        lot = make_bake_lot(api, line["id"], oven["id"], baked_qty=5,
                            produced_at="2026-06-30T06:00:00Z",
                            slot_start="2026-06-30T02:00:00Z", slot_end="2026-06-30T03:00:00Z")
        expired = get_success_data(api.expire_bake_lot(lot["id"], MANAGER))
        # State-check precedes OCC; a PRD-only reader may report either the expired guard
        # or the generic invalid-state error for a transition undefined from EXPIRED.
        validate_error_is_one_of(
            api.markdown_bake_lot(lot["id"], {"expected_bake_lot_version": expired["version"]}, MANAGER),
            [ApiErrorId.ERR_LOT_EXPIRED.value, ApiErrorId.ERR_INVALID_STATE.value])
