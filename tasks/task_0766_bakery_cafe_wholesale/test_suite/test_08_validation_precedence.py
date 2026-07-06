"""Validation precedence on order creation and the allergen safety boundary."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, setup_committed_line_with_account, make_standing_order,
    set_clock, TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]


class TestReferentialVsTemporalPrecedence:
    def test_discontinued_product_pre_empts_past_cutoff(self, api):
        """PRD 2.8: precedence "6. Referential business rules — product discontinuation
        (ERR_PRODUCT_DISCONTINUED) ... 8. Temporal constraints (ERR_PAST_CUTOFF ...)." PRD
        3.1: "Once a product is DISCONTINUED, it may no longer be named on a new bake-plan
        line, a new standing order, or a new delivery order — such attempts are rejected
        with ERR_PRODUCT_DISCONTINUED."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_temporal_on_create_order
        """
        ctx = setup_committed_line_with_account(api, par_qty=20,
                                                production_date="2026-06-10T00:00:00Z")
        so = make_standing_order(api, ctx["account"]["id"], ctx["product"]["id"],
                                 qty_per_delivery=5, weekday_mask=["WED"], cutoff_hours=24)
        validate_success(api.discontinue_product(ctx["product"]["id"], MANAGER))
        set_clock(api, "2026-06-10T00:00:00Z")   # only 10h before delivery => inside cutoff
        validate_error(api.create_delivery_order({
            "wholesale_account_id": ctx["account"]["id"], "product_id": ctx["product"]["id"],
            "bake_plan_line_id": ctx["line"]["id"], "delivery_date": "2026-06-10T10:00:00Z",
            "qty": 5, "standing_order_id": so["id"]}, MANAGER),
            ApiErrorId.ERR_PRODUCT_DISCONTINUED.value)

    def test_past_cutoff_fires_in_isolation(self, api):
        """PRD 3.7: "For an order citing a standing order, the current clock must be at
        least cutoff_hours before the delivery_date; an order placed inside that lead-time
        window is refused with ERR_PAST_CUTOFF."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_temporal_on_create_order
        """
        ctx = setup_committed_line_with_account(api, par_qty=20,
                                                production_date="2026-06-10T00:00:00Z")
        so = make_standing_order(api, ctx["account"]["id"], ctx["product"]["id"],
                                 qty_per_delivery=5, weekday_mask=["WED"], cutoff_hours=24)
        set_clock(api, "2026-06-10T00:00:00Z")   # 10h before delivery, product still ACTIVE
        validate_error(api.create_delivery_order({
            "wholesale_account_id": ctx["account"]["id"], "product_id": ctx["product"]["id"],
            "bake_plan_line_id": ctx["line"]["id"], "delivery_date": "2026-06-10T10:00:00Z",
            "qty": 5, "standing_order_id": so["id"]}, MANAGER),
            ApiErrorId.ERR_PAST_CUTOFF.value)


class TestAllergenSafety:
    def test_order_conflicting_with_account_restriction_is_rejected(self, api):
        """PRD 3.6: "The allergen_restrictions set is a hard safety boundary: ordering a
        product whose allergens intersect the account's restrictions is refused with
        ERR_ALLERGEN_CONFLICT, and this allergen check guards both delivery-order creation
        and standing-order creation."

        Design: Corner/validations/allergen_conflict_on_create_order_returns_error
        """
        ctx = setup_committed_line_with_account(
            api, par_qty=10, allergens=["NUT", "GLUTEN"], allergen_restrictions=["NUT"],
            production_date="2026-06-25T00:00:00Z")
        validate_error(api.create_delivery_order({
            "wholesale_account_id": ctx["account"]["id"], "product_id": ctx["product"]["id"],
            "bake_plan_line_id": ctx["line"]["id"], "delivery_date": "2026-06-25T10:00:00Z",
            "qty": 2}, MANAGER), ApiErrorId.ERR_ALLERGEN_CONFLICT.value)
