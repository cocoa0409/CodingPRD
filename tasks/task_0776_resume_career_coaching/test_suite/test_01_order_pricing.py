"""Order pricing: provisional vs final quotes, the tiered/rush/coupon formula,
the volume-discount threshold, and the confirmation charge."""
from test_helpers import (
    validate_success,
    setup_confirmed_order,
    setup_drafted_deliverable,
    create_plan,
    create_client_entity,
    create_order_payload,
    make_client_headers,
    open_revision,
    draft,
    approve,
    api_client,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]

PRO_DUAL_PLAN = {
    "tier": "PRO",
    "base_price_cents": 50000,
    "included_deliverables": ["RESUME"],
    "included_revision_rounds": 2,
    "included_coaching_sessions": 0,
    "includes_ats": True,
    "guarantee_type": "SATISFACTION",
    "rush_surcharge_pct": 0.30,
}


def _drive_to_ready_with_overage_revision(ctx):
    """From a drafted deliverable, run three revision rounds (the 3rd a billable
    overage under included_revision_rounds=2), then approve so the order is READY."""
    deliv_id = ctx["deliverable_id"]
    for reason in ("tighten summary", "reorder experience", "one more pass"):
        open_revision(deliv_id, ctx["client_headers"], reason=reason)
        draft(deliv_id, ctx["coach_headers"])
    approve(deliv_id, ctx["client_headers"])


class TestProvisionalVsFinal:
    def test_provisional_quote_excludes_production_overage(self, api):
        """PRD §3.2: "The provisional quote is the order-price calculation evaluated
        over only the intake-time add-ons." The order has no intake add-ons, so the
        provisional total is just the base price.

        Design: Difficulty/dual_variant_calc/order_pricing_provisional_vs_final
        """
        ctx = setup_drafted_deliverable(plan_overrides=PRO_DUAL_PLAN)
        order = api.get_order(ctx["order_id"], ADMIN)
        data = validate_success(order)
        assert data["provisional_total_cents"] == 50000, (
            f"provisional should be base 50000, got {data['provisional_total_cents']}"
        )

    def test_final_quote_includes_overage_revision_addon(self, api):
        """PRD §3.3: "the final variant includes every add-on on the order whose
        status is not CANCELLED at delivery time, which is to say it also captures
        the overage EXTRA_REVISION and EXTRA_COACHING add-ons generated during
        production, whereas the provisional variant saw only the intake-time add-ons."

        Design: Difficulty/dual_variant_calc/order_pricing_provisional_vs_final
        """
        ctx = setup_drafted_deliverable(plan_overrides=PRO_DUAL_PLAN)
        _drive_to_ready_with_overage_revision(ctx)
        delivered = validate_success(api.deliver_order(ctx["order_id"], ADMIN))
        assert delivered["final_total_cents"] == 54000, (
            f"final should be base 50000 + overage 4000, got {delivered['final_total_cents']}"
        )
        assert delivered["final_total_cents"] != delivered["provisional_total_cents"], (
            "final quote must differ from provisional once a production overage accrues"
        )


class TestCombinatorialQuote:
    def _make_rush_coupon_order(self, api):
        plan = create_plan(
            tier="EXECUTIVE", base_price_cents=80000, included_deliverables=["RESUME"],
            included_revision_rounds=1, included_coaching_sessions=0, guarantee_type="NONE",
            rush_surcharge_pct=0.30,
        )
        client = create_client_entity(email="cleo@x.com")
        payload = create_order_payload(
            plan["id"], target_role="VP Eng", target_industry="Finance",
            requested_delivery_days=5, rush=True, coupon_code="WELCOME10",
            addon_types=["EXTRA_COACHING", "EXTRA_DELIVERABLE", "INTERVIEW_PREP"],
        )
        return validate_success(api.create_order(payload, make_client_headers(client["id"])), 201)

    def test_provisional_total_with_volume_discount_coupon_and_rush(self, api):
        """PRD §3.2: "an add-on volume discount applies only when the add-on count is
        at least three: in that case the discount is the add-on subtotal multiplied by
        ten percent, rounded half up; otherwise it is zero." The three intake add-ons
        (36000) attract the 10% volume discount, WELCOME10 discounts the base, and the
        rush surcharge is applied last to the discounted subtotal.

        Design: Difficulty/combinatorial_formula/order_quote_nonlinear_tiered_rush_coupon
        """
        data = self._make_rush_coupon_order(api)
        assert data["addons_subtotal_cents"] == 36000
        assert data["provisional_total_cents"] == 135720, (
            f"expected 135720, got {data['provisional_total_cents']}"
        )

    def test_discount_and_rush_components_of_quote(self, api):
        """PRD §3.2: "Finally the rush surcharge is applied last, to the discounted
        subtotal: when the order is a rush, rush_surcharge_cents is the discounted
        subtotal multiplied by the plan's rush_surcharge_pct, rounded half up; otherwise
        it is zero." discount_cents fuses the 3600 volume discount and the 8000 WELCOME10
        coupon; the rush surcharge is 30% of the 104400 discounted subtotal.

        Design: Difficulty/combinatorial_formula/order_quote_nonlinear_tiered_rush_coupon
        """
        data = self._make_rush_coupon_order(api)
        assert data["discount_cents"] == 11600, f"expected 11600, got {data['discount_cents']}"
        assert data["rush_surcharge_cents"] == 31320, (
            f"expected 31320, got {data['rush_surcharge_cents']}"
        )


def test_volume_discount_not_applied_below_three_addons(api):
    """PRD §3.2: "an add-on volume discount applies only when the add-on count is at
    least three ... otherwise it is zero." With only two intake add-ons the discount
    is zero and the provisional total is base plus the add-on subtotal.

    Design: Corner/calculations/volume_discount_not_applied_below_three_addons
    """
    plan = create_plan(
        tier="PRO", base_price_cents=30000, included_deliverables=["RESUME"],
        included_revision_rounds=1, included_coaching_sessions=0, guarantee_type="NONE",
    )
    client = create_client_entity(email="jo@x.com")
    payload = create_order_payload(
        plan["id"], addon_types=["EXTRA_COACHING", "EXTRA_DELIVERABLE"],
    )
    data = validate_success(api.create_order(payload, make_client_headers(client["id"])), 201)
    assert data["addons_subtotal_cents"] == 21000
    assert data["discount_cents"] == 0
    assert data["provisional_total_cents"] == 51000


def test_confirm_charge_visible_in_same_response(api):
    """PRD §3.3: "Confirming writes a single `CHARGE` payment for the provisional total
    with reason `CONFIRM`, so `amount_charged_cents` rises by `provisional_total_cents`".
    The confirm response itself already reflects the charge and the IN_PRODUCTION state.

    Design: Corner/consistency_model/confirm_charge_visible_in_same_response
    """
    plan = create_plan(
        tier="BASIC", base_price_cents=20000, included_deliverables=["RESUME"],
        included_revision_rounds=1, included_coaching_sessions=0, guarantee_type="NONE",
    )
    client = create_client_entity(email="xi@x.com")
    ch = make_client_headers(client["id"])
    order = validate_success(api.create_order(create_order_payload(plan["id"]), ch), 201)
    confirmed = validate_success(api.confirm_order(order["id"], ch))
    assert confirmed["status"] == "IN_PRODUCTION"
    assert confirmed["amount_charged_cents"] == 20000
